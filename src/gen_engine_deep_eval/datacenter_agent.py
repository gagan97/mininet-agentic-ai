"""Agentic Mininet integration for LLM-driven data-center remediation.

This module provides a production-style topology blueprint, import/export
support, and tool wrappers that allow an LLM-driven ReAct agent to reason
about outages across a multi-tier (core/aggregation/access) Mininet lab.  The
agent can:

* inspect detailed topology metadata (roles, models, link media/speeds)
* monitor synthetic utilisation metrics for each link and port
* simulate failures such as fibre cuts, cable unplug events, congestion spikes,
  and latency inflation
* activate backup paths and later restore the primary design intent once the
  failure is cleared
* persist and reload topology state for reproducible incident drills

The implementation keeps Mininet imports lazy so that unit tests can exercise
blueprint logic without requiring a Mininet install.  When running the agent for
real you must install Mininet (typically on Ubuntu/Debian) and execute with root
privileges.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from importlib import import_module
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available, skip loading .env file
    pass
from typing import Any, Dict, List, Literal, Tuple

from langchain.agents import AgentExecutor, Tool, create_react_agent
from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from loguru import logger
from pydantic.v1 import BaseModel, Field

import networkx as nx
from .wrapper import GenerativeEngineLLM

NodeRole = Literal["core", "aggregation", "access", "host"]
LinkType = Literal[
    "core-aggregation",
    "aggregation-aggregation",
    "aggregation-access",
    "access-access",
    "access-host",
]
FailureMode = Literal[
    "cable_cut",
    "cable_unplug",
    "latency_spike",
    "congestion",
    "packet_loss",
]


@dataclass(slots=True)
class NodeSpec:
    name: str
    role: NodeRole
    model: str
    node_type: Literal["switch", "host"]
    port_speed_gbps: float | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeSpec":
        return cls(**data)


@dataclass(slots=True)
class LinkSpec:
    src: str
    dst: str
    link_type: LinkType
    port_speed_gbps: float
    medium: Literal["fiber", "copper"] = "fiber"
    delay_ms: int = 2
    loss_percent: float = 0.0
    description: str | None = None

    def key(self) -> Tuple[str, str]:
        return tuple(sorted((self.src, self.dst)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkSpec":
        return cls(**data)


@dataclass(slots=True)
class TopologyBlueprint:
    name: str
    nodes: List[NodeSpec]
    links: List[LinkSpec]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [node.to_dict() for node in self.nodes],
            "links": [link.to_dict() for link in self.links],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TopologyBlueprint":
        return cls(
            name=data["name"],
            nodes=[NodeSpec.from_dict(node) for node in data["nodes"]],
            links=[LinkSpec.from_dict(link) for link in data["links"]],
        )


@dataclass(slots=True)
class LinkProfile:
    bw_gbps: float
    delay_ms: int
    loss_percent: float
    utilisation_percent: float = 0.0
    status: Literal["up", "down"] = "up"
    throughput_gbps: float | None = None
    observed_rtt_ms: float | None = None
    last_sample_timestamp: float | None = None
    last_sample_bytes: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_datacenter_blueprint() -> TopologyBlueprint:
    nodes: List[NodeSpec] = [
        NodeSpec("core1", role="core", model="Cisco Nexus 9500", node_type="switch", port_speed_gbps=100),
        NodeSpec("core2", role="core", model="Cisco Nexus 9500", node_type="switch", port_speed_gbps=100),
    ]

    for idx in range(1, 3):
        for suffix in ("a", "b"):
            nodes.append(
                NodeSpec(
                    name=f"agg{idx}{suffix}",
                    role="aggregation",
                    model="Arista 7280R3",
                    node_type="switch",
                    port_speed_gbps=40,
                    metadata={"pod": idx, "plane": suffix},
                )
            )

    for pod in range(1, 3):
        for row in range(1, 3):
            for suffix in ("a", "b"):
                nodes.append(
                    NodeSpec(
                        name=f"acc{pod}{row}{suffix}",
                        role="access",
                        model="Cisco Catalyst 9300",
                        node_type="switch",
                        port_speed_gbps=10,
                        metadata={"pod": pod, "row": row, "pair": suffix},
                    )
                )

    host_idx = 1
    for access in [node for node in nodes if node.role == "access"]:
        for port in range(1, 3):
            nodes.append(
                NodeSpec(
                    name=f"h{host_idx}",
                    role="host",
                    model="Dell PowerEdge R760",
                    node_type="host",
                    port_speed_gbps=10,
                    metadata={"parent": access.name, "rack_unit": port},
                )
            )
            host_idx += 1

    links: List[LinkSpec] = []
    aggregation_switches = [node for node in nodes if node.role == "aggregation"]
    for core in [node for node in nodes if node.role == "core"]:
        for agg in aggregation_switches:
            links.append(
                LinkSpec(
                    src=core.name,
                    dst=agg.name,
                    link_type="core-aggregation",
                    port_speed_gbps=40,
                    medium="fiber",
                    delay_ms=2,
                    description="Spine uplink",
                )
            )

    for agg in aggregation_switches:
        pod = agg.metadata["pod"]
        access_layer = [
            node for node in nodes if node.role == "access" and node.metadata["pod"] == pod
        ]
        for access in access_layer:
            links.append(
                LinkSpec(
                    src=agg.name,
                    dst=access.name,
                    link_type="aggregation-access",
                    port_speed_gbps=10,
                    medium="fiber",
                    delay_ms=3,
                    description=f"Pod {pod} uplink",
                )
            )

    access_switches = [node for node in nodes if node.role == "access"]
    for idx in range(0, len(access_switches), 2):
        a = access_switches[idx]
        b = access_switches[idx + 1]
        links.append(
            LinkSpec(
                src=a.name,
                dst=b.name,
                link_type="access-access",
                port_speed_gbps=10,
                medium="copper",
                delay_ms=1,
                description="Access pair cross-link",
            )
        )

    for host in [node for node in nodes if node.role == "host"]:
        parent = host.metadata["parent"]
        links.append(
            LinkSpec(
                src=host.name,
                dst=parent,
                link_type="access-host",
                port_speed_gbps=10,
                medium="copper",
                delay_ms=1,
                description="Server NIC",
            )
        )

    return TopologyBlueprint(name="pod2-spine-leaf", nodes=nodes, links=links)


def _ensure_mininet_imports():
    try:
        net_mod = import_module("mininet.net")
        topo_mod = import_module("mininet.topo")
        link_mod = import_module("mininet.link")
        node_mod = import_module("mininet.node")
    except ImportError as exc:  # pragma: no cover - runtime requirement
        raise RuntimeError(
            "Mininet is required for this agent. Install it from https://github.com/mininet/mininet"
        ) from exc

    return (
        net_mod.Mininet,
        topo_mod.Topo,
        link_mod.TCLink,
        node_mod.Controller,
        node_mod.OVSKernelSwitch,
    )


@dataclass(slots=True)
class DataCenterEnvironment(AbstractContextManager["DataCenterEnvironment"]):
    blueprint: TopologyBlueprint = field(default_factory=build_datacenter_blueprint)
    utilisation_decay: float = 0.9

    def __post_init__(self) -> None:
        (
            self._mininet_cls,
            self._topo_base,
            self._tc_link,
            self._controller,
            self._switch_cls,
        ) = _ensure_mininet_imports()
        self.net = None
        self.link_profiles: Dict[Tuple[str, str], LinkProfile] = {}
        self._baseline_profiles: Dict[Tuple[str, str], LinkProfile] = {}
        self._link_metric_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._topology_graph: nx.Graph | None = None

    def __enter__(self) -> "DataCenterEnvironment":
        self.start()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:  # pragma: no cover
        self.stop()

    def start(self) -> None:
        if self.net is not None:
            return
        if os.geteuid() != 0:  # pragma: no cover
            raise PermissionError("Mininet must run as root. Re-run with sudo.")
        topo_cls = self._build_topology_class()
        logger.info("Starting Mininet with blueprint '%s'", self.blueprint.name)
        self.net = self._mininet_cls(
            topo=topo_cls(),
            controller=self._controller,
            switch=self._switch_cls,
            link=self._tc_link,
            autoSetMacs=True,
            autoStaticArp=True,
            build=False,
        )
        self.net.build()
        self.net.start()
        self._initialise_profiles()

    def stop(self) -> None:
        if self.net is not None:
            logger.info("Stopping Mininet network")
            self.net.stop()
            self.net = None
            self.link_profiles.clear()
            self._baseline_profiles.clear()
            self._link_metric_cache.clear()
            self._topology_graph = None

    def _build_topology_class(self):  # pragma: no cover
        blueprint = self.blueprint
        tc_link = self._tc_link
        topo_base = self._topo_base

        class BlueprintTopo(topo_base):
            def build(self):  # type: ignore[override]
                for node in blueprint.nodes:
                    if node.node_type == "host":
                        self.addHost(node.name)
                    else:
                        self.addSwitch(node.name)
                for link in blueprint.links:
                    self.addLink(
                        link.src,
                        link.dst,
                        cls=tc_link,
                        bw=link.port_speed_gbps,
                        delay=f"{link.delay_ms}ms",
                        loss=link.loss_percent,
                    )

        return BlueprintTopo

    def _initialise_profiles(self) -> None:
        assert self.net is not None
        for link in self.blueprint.links:
            key = link.key()
            profile = LinkProfile(
                bw_gbps=link.port_speed_gbps,
                delay_ms=link.delay_ms,
                loss_percent=link.loss_percent,
                utilisation_percent=random.uniform(5.0, 15.0),
            )
            self.link_profiles[key] = profile
            self._baseline_profiles[key] = LinkProfile(**profile.to_dict())

    def export_state(self) -> Dict[str, Any]:
        return {
            "blueprint": self.blueprint.to_dict(),
            "links": {"-".join(key): profile.to_dict() for key, profile in self.link_profiles.items()},
        }

    def save_state(self, path: str | Path) -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.export_state(), indent=2))
        logger.info("Saved topology state to %s", p)
        return p

    @classmethod
    def load_state(cls, path: str | Path) -> "DataCenterEnvironment":
        data = json.loads(Path(path).read_text())
        blueprint = TopologyBlueprint.from_dict(data["blueprint"])
        env = cls(blueprint=blueprint)
        env.link_profiles = {
            tuple(key.split("-")): LinkProfile(**profile)
            for key, profile in data.get("links", {}).items()
        }
        env._baseline_profiles = {
            key: LinkProfile(**profile.to_dict())
            for key, profile in env.link_profiles.items()
        }
        return env

    def update_utilisation(self) -> None:
        for profile in self.link_profiles.values():
            delta = random.uniform(-3.0, 6.0)
            profile.utilisation_percent = max(
                0.0,
                min(100.0, profile.utilisation_percent * self.utilisation_decay + delta),
            )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "blueprint": self.blueprint.to_dict(),
            "link_state": {"-".join(key): profile.to_dict() for key, profile in self.link_profiles.items()},
        }

    def monitor_link(self, params: str) -> str:
        data = self._loads(params)
        src, dst = data.get("src"), data.get("dst")
        if not src or not dst:
            raise ValueError("monitor_link requires 'src' and 'dst'")
        key = self._link_key(src, dst)
        profile = self.link_profiles.get(key)
        if profile is None:
            raise ValueError(f"Unknown link {src}-{dst}")
        self.update_utilisation()
        metrics: Dict[str, Any] | None = None
        if self.net is not None:
            try:
                metrics = self._sample_link_metrics(src, dst)
            except Exception as exc:  # pragma: no cover - best effort sampling
                logger.debug("Failed to sample metrics for %s-%s: %s", src, dst, exc)
        payload = {
            "tool": "monitor_link",
            "link": [src, dst],
            "status": profile.status,
            "bw_gbps": profile.bw_gbps,
            "delay_ms": profile.delay_ms,
            "loss_percent": profile.loss_percent,
            "utilisation_percent": round(profile.utilisation_percent, 2),
            "within_baseline": profile.utilisation_percent < 70,
            "throughput_gbps": profile.throughput_gbps,
            "observed_rtt_ms": profile.observed_rtt_ms,
        }
        if metrics is not None:
            payload["samples"] = metrics
        return json.dumps(payload)

    def probe_connectivity(self, params: str) -> str:
        if self.net is None:
            raise RuntimeError("Network is not running")
        data = self._loads(params)
        src = data.get("src")
        dst = data.get("dst")
        if not src or not dst:
            raise ValueError("probe_connectivity requires 'src' and 'dst'")
        count = int(data.get("count", 3))
        src_host = self.net.get(src)
        dst_host = self.net.get(dst)
        logger.info("Pinging between %s and %s (%s packets)", src, dst, count)
        loss = self.net.ping([src_host, dst_host], timeout=1)
        result = {
            "tool": "probe_connectivity",
            "src": src,
            "dst": dst,
            "loss_percent": loss,
            "success": loss == 0.0,
        }
        return json.dumps(result)

    def traceroute(self, params: str) -> str:
        if self.net is None:
            raise RuntimeError("Network is not running")
        data = self._loads(params)
        src = data.get("src")
        dst = data.get("dst")
        if not src or not dst:
            raise ValueError("traceroute requires 'src' and 'dst'")
        host = self.net.get(src)
        logger.info("Running traceroute from %s to %s", src, dst)
        output = host.cmd(f"traceroute -n {dst}")
        return json.dumps({"tool": "traceroute", "src": src, "dst": dst, "output": output})

    def simulate_failure(self, params: str) -> str:
        data = self._loads(params)
        src, dst = data.get("src"), data.get("dst")
        mode: FailureMode = data.get("mode", "cable_cut")
        severity = float(data.get("severity", 1.0))
        if not src or not dst:
            raise ValueError("simulate_failure requires 'src' and 'dst'")
        key = self._link_key(src, dst)
        profile = self.link_profiles.get(key)
        if profile is None:
            raise ValueError(f"Unknown link {src}-{dst}")

        if mode in {"cable_cut", "cable_unplug"}:
            self._set_link_state(src, dst, "down")
            profile.status = "down"
        elif mode == "latency_spike":
            extra_delay = int(max(1, severity * 20))
            self._apply_link_profile(src, dst, delay_ms=profile.delay_ms + extra_delay)
        elif mode == "congestion":
            reduced_bw = max(1.0, profile.bw_gbps * (1 - 0.5 * severity))
            self._apply_link_profile(src, dst, bw_gbps=reduced_bw)
            profile.utilisation_percent = min(100.0, profile.utilisation_percent + 30 * severity)
        elif mode == "packet_loss":
            new_loss = min(100.0, profile.loss_percent + 5 * severity)
            self._apply_link_profile(src, dst, loss_percent=new_loss)
        else:  # pragma: no cover
            raise ValueError(f"Unsupported failure mode {mode}")

        payload = {
            "tool": "simulate_failure",
            "link": [src, dst],
            "mode": mode,
            "profile": self.link_profiles[key].to_dict(),
        }
        return json.dumps(payload)

    def activate_backup_path(self, params: str) -> str:
        data = self._loads(params)
        path = data.get("path")
        if not path or not isinstance(path, list) or len(path) < 2:
            raise ValueError("activate_backup_path requires a 'path' list of nodes")
        for hop_a, hop_b in zip(path, path[1:]):
            key = self._link_key(hop_a, hop_b)
            if key not in self.link_profiles:
                raise ValueError(f"Unknown hop {hop_a}-{hop_b}")
            self._set_link_state(hop_a, hop_b, "up")
            profile = self.link_profiles[key]
            profile.status = "up"
            self._apply_link_profile(hop_a, hop_b, bw_gbps=max(profile.bw_gbps, 5.0))
        return json.dumps({"tool": "activate_backup_path", "path": path})

    def restore_primary_path(self, params: str) -> str:
        data = self._loads(params)
        src, dst = data.get("src"), data.get("dst")
        if not src or not dst:
            raise ValueError("restore_primary_path requires 'src' and 'dst'")
        key = self._link_key(src, dst)
        baseline = self._baseline_profiles.get(key)
        if baseline is None:
            raise ValueError(f"No baseline profile recorded for {src}-{dst}")
        self._apply_link_profile(src, dst, **baseline.to_dict())
        self._set_link_state(src, dst, baseline.status)
        self.link_profiles[key] = LinkProfile(**baseline.to_dict())
        self._topology_graph = None
        return json.dumps({"tool": "restore_primary_path", "link": [src, dst], "profile": baseline.to_dict()})

    def _set_link_state(self, src: str, dst: str, state: Literal["up", "down"]) -> None:
        if self.net is None:
            self._topology_graph = None
            return
        logger.info("Setting link %s-%s -> %s", src, dst, state)
        self.net.configLinkStatus(src, dst, state)
        self._topology_graph = None

    def _apply_link_profile(
        self,
        src: str,
        dst: str,
        bw_gbps: float | None = None,
        delay_ms: int | None = None,
        loss_percent: float | None = None,
        status: Literal["up", "down"] | None = None,
    ) -> None:
        key = self._link_key(src, dst)
        profile = self.link_profiles[key]
        updates = {}
        if bw_gbps is not None:
            profile.bw_gbps = bw_gbps
            updates["bw"] = bw_gbps
        if delay_ms is not None:
            profile.delay_ms = delay_ms
            updates["delay"] = f"{delay_ms}ms"
        if loss_percent is not None:
            profile.loss_percent = loss_percent
            updates["loss"] = loss_percent
        if status is not None:
            profile.status = status
        if self.net is None:
            return
        if updates:
            link = self._get_mininet_link(src, dst)
            for intf in (link.intf1, link.intf2):
                intf.config(**updates)
        if status is not None:
            self._set_link_state(src, dst, status)
        self._topology_graph = None

    @staticmethod
    def _link_key(src: str, dst: str) -> Tuple[str, str]:
        return tuple(sorted((src, dst)))

    def _get_mininet_link(self, src: str, dst: str):
        if self.net is None:
            raise RuntimeError("Network is not running")

        links = self.net.linksBetween(src, dst)
        if links:
            return links[0]

        # Fallback: traverse interfaces on source node to locate the link
        src_node = self.net.get(src)
        dst_node = self.net.get(dst)
        if not src_node or not dst_node:
            raise ValueError(f"Unknown nodes {src} or {dst}")

        for intf in src_node.intfList():
            link = getattr(intf, "link", None)
            if not link or not getattr(link, "intf1", None) or not getattr(link, "intf2", None):
                continue
            other_node = link.intf1.node if link.intf1.node != src_node else link.intf2.node
            if other_node == dst_node:
                return link

        raise ValueError(f"No Mininet link between {src} and {dst}")

    def _get_link_interfaces(self, src: str, dst: str):  # pragma: no cover - requires Mininet runtime
        link = self._get_mininet_link(src, dst)
        return link.intf1, link.intf2

    @staticmethod
    def _read_sysfs_counter(intf_name: str, counter: str) -> int | None:
        path = Path("/sys/class/net") / intf_name / "statistics" / counter
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):  # pragma: no cover - filesystem access guarded
            return None

    def _collect_interface_stats(self, intf) -> Dict[str, Any]:  # pragma: no cover - requires Mininet runtime
        stats: Dict[str, Any] = {}

        try:
            raw_stats = intf.stats()
        except Exception:  # pragma: no cover - defensive
            raw_stats = {}

        for key in ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets", "rx_errors", "tx_errors"):
            value = raw_stats.get(key)
            if value is None:
                value = self._read_sysfs_counter(intf.name, key)
            stats[key] = value

        try:
            qdisc_output = intf.tc("qdisc", "show", "dev", intf.name)
        except Exception:  # pragma: no cover - defensive
            qdisc_output = ""

        drop_match = re.search(r"dropped (?P<drops>\d+)", qdisc_output)
        stats["dropped_packets"] = int(drop_match.group("drops")) if drop_match else None

        backlog_match = re.search(r"backlog (?P<backlog_bytes>\d+)b?(?:\s+(?P<backlog_packets>\d+)p)?", qdisc_output)
        if backlog_match:
            stats["backlog_bytes"] = int(backlog_match.group("backlog_bytes"))
            backlog_packets = backlog_match.group("backlog_packets")
            stats["backlog_packets"] = int(backlog_packets) if backlog_packets is not None else None
        else:
            stats["backlog_bytes"] = None
            stats["backlog_packets"] = None

        stats["timestamp"] = time.time()
        stats["interface"] = intf.name
        stats["node"] = getattr(getattr(intf, "node", None), "name", None)
        return stats

    def _sample_link_metrics(self, src: str, dst: str) -> Dict[str, Any]:  # pragma: no cover - requires Mininet runtime
        if self.net is None:
            raise RuntimeError("Network is not running")

        key = self._link_key(src, dst)
        profile = self.link_profiles.get(key)
        if profile is None:
            raise ValueError(f"Unknown link {src}-{dst}")

        intf_a, intf_b = self._get_link_interfaces(src, dst)
        stats_a = self._collect_interface_stats(intf_a)
        stats_b = self._collect_interface_stats(intf_b)

        timestamp = max(stats_a.get("timestamp", time.time()), stats_b.get("timestamp", time.time()))
        cache = self._link_metric_cache.get(key)

        throughput_gbps = None
        node_a = stats_a.get("node") or stats_a.get("interface")
        node_b = stats_b.get("node") or stats_b.get("interface")

        if node_a == src:
            src_stats, dst_stats = stats_a, stats_b
        elif node_b == src:
            src_stats, dst_stats = stats_b, stats_a
        elif node_a == dst:
            src_stats, dst_stats = stats_b, stats_a
        elif node_b == dst:
            src_stats, dst_stats = stats_a, stats_b
        else:
            src_stats, dst_stats = stats_a, stats_b

        direction_stats = {
            "src": src_stats,
            "dst": dst_stats,
        }

        if cache:
            delta_t = timestamp - cache.get("timestamp", timestamp)
            if delta_t > 0:
                tx_delta = 0
                for label, current in (("a", stats_a), ("b", stats_b)):
                    prev_tx = cache.get(f"{label}_tx_bytes")
                    curr_tx = current.get("tx_bytes")
                    if prev_tx is not None and curr_tx is not None and curr_tx >= prev_tx:
                        tx_delta += curr_tx - prev_tx
                throughput_gbps = (tx_delta * 8) / (delta_t * 1e9) if tx_delta else 0.0

        # Update cache for next sample
        estimated_rtt_ms = None
        if profile.delay_ms is not None:
            estimated_rtt_ms = profile.delay_ms * 2
            backlog_bytes_total = 0
            for sample in (src_stats, dst_stats):
                backlog_bytes_total += sample.get("backlog_bytes") or 0
            if backlog_bytes_total and profile.bw_gbps:
                bytes_per_ms = (profile.bw_gbps * 1e9 / 8) / 1000
                if bytes_per_ms:
                    estimated_rtt_ms += backlog_bytes_total / bytes_per_ms

        self._link_metric_cache[key] = {
            "timestamp": timestamp,
            "a_tx_bytes": stats_a.get("tx_bytes"),
            "a_rx_bytes": stats_a.get("rx_bytes"),
            "b_tx_bytes": stats_b.get("tx_bytes"),
            "b_rx_bytes": stats_b.get("rx_bytes"),
        }

        profile.last_sample_timestamp = timestamp
        profile.last_sample_bytes = {
            "src_tx": src_stats.get("tx_bytes"),
            "src_rx": src_stats.get("rx_bytes"),
            "dst_tx": dst_stats.get("tx_bytes"),
            "dst_rx": dst_stats.get("rx_bytes"),
        }
        profile.throughput_gbps = throughput_gbps
        profile.observed_rtt_ms = estimated_rtt_ms

        utilisation_percent = None
        if throughput_gbps is not None and profile.bw_gbps:
            utilisation_percent = min(100.0, (throughput_gbps / profile.bw_gbps) * 100)

        return {
            "link": [src, dst],
            "timestamp": timestamp,
            "throughput_gbps": throughput_gbps,
            "expected_capacity_gbps": profile.bw_gbps,
            "utilisation_percent": utilisation_percent,
            "estimated_rtt_ms": estimated_rtt_ms,
            "interfaces": direction_stats,
        }

    def inspect_link_health(self, params: str) -> str:
        data = self._loads(params)
        src, dst = data.get("src"), data.get("dst")
        if not src or not dst:
            raise ValueError("inspect_link_health requires 'src' and 'dst'")
        key = self._link_key(src, dst)
        profile = self.link_profiles.get(key)
        if profile is None:
            raise ValueError(f"Unknown link {src}-{dst}")

        metrics: Dict[str, Any] | None = None
        if self.net is not None:
            metrics = self._sample_link_metrics(src, dst)

        payload = {
            "tool": "inspect_link_health",
            "link": [src, dst],
            "profile": profile.to_dict(),
            "metrics": metrics,
        }
        return json.dumps(payload)

    def _get_topology_graph(self, include_down: bool = False) -> nx.Graph:
        if not include_down and self._topology_graph is not None:
            return self._topology_graph

        graph = nx.Graph()
        for node in self.blueprint.nodes:
            graph.add_node(
                node.name,
                role=node.role,
                model=node.model,
                metadata=node.metadata,
            )

        for link in self.blueprint.links:
            key = link.key()
            profile = self.link_profiles.get(key)
            status = profile.status if profile else "unknown"
            if status != "up" and not include_down:
                continue

            bw_gbps = profile.bw_gbps if profile else link.port_speed_gbps
            throughput = profile.throughput_gbps if profile else None
            available_bw = None
            if bw_gbps is not None:
                available_bw = max(bw_gbps - (throughput or 0.0), 0.0)

            latency_weight = None
            if profile and profile.observed_rtt_ms is not None:
                latency_weight = profile.observed_rtt_ms
            elif profile:
                latency_weight = profile.delay_ms
            else:
                latency_weight = link.delay_ms

            graph.add_edge(
                link.src,
                link.dst,
                status=status,
                delay_ms=profile.delay_ms if profile else link.delay_ms,
                loss_percent=profile.loss_percent if profile else link.loss_percent,
                bw_gbps=bw_gbps,
                throughput_gbps=throughput,
                available_bw_gbps=available_bw,
                utilisation_percent=profile.utilisation_percent if profile else None,
                weight_latency=latency_weight,
            )

        if include_down:
            return graph

        self._topology_graph = graph
        return graph

    def compute_shortest_path(
        self,
        src: str,
        dst: str,
        *,
        avoid: List[Tuple[str, str]] | None = None,
        objective: Literal["latency", "capacity"] = "latency",
        include_down: bool = False,
    ) -> Dict[str, Any]:
        graph = self._get_topology_graph(include_down=True).copy()

        if not include_down:
            to_remove = [(u, v) for u, v, data in graph.edges(data=True) if data.get("status") != "up"]
            graph.remove_edges_from(to_remove)

        if avoid:
            for edge in avoid:
                if len(edge) != 2:
                    continue
                u, v = edge
                if graph.has_edge(u, v):
                    graph.remove_edge(u, v)

        if objective == "latency":
            weight = "weight_latency"
        elif objective == "capacity":

            def inverse_capacity(u, v, data):
                bw = data.get("available_bw_gbps")
                if bw is None or bw <= 0:
                    bw = data.get("bw_gbps")
                if bw is None or bw <= 0:
                    return float("inf")
                return 1 / bw

            weight = inverse_capacity
        else:  # pragma: no cover - guarded by typing
            raise ValueError(f"Unsupported objective '{objective}'")

        try:
            path = nx.shortest_path(graph, src, dst, weight=weight)
        except nx.NetworkXNoPath as exc:
            raise ValueError(f"No path available between {src} and {dst}") from exc

        edges = list(zip(path, path[1:]))
        total_latency = 0.0
        min_available_bw = float("inf")
        for u, v in edges:
            data = graph[u][v]
            latency = data.get("weight_latency")
            if latency is not None:
                total_latency += latency
            available = data.get("available_bw_gbps")
            if available is None:
                available = data.get("bw_gbps")
            if available is not None:
                min_available_bw = min(min_available_bw, available)

        if min_available_bw == float("inf"):
            min_available_bw = None

        return {
            "path": path,
            "hops": edges,
            "total_latency_ms": total_latency if total_latency else None,
            "min_available_bw_gbps": min_available_bw,
            "objective": objective,
        }

    def compute_resilient_path(self, params: str) -> str:
        data = self._loads(params)
        src, dst = data.get("src"), data.get("dst")
        if not src or not dst:
            raise ValueError("compute_resilient_path requires 'src' and 'dst'")
        avoid = data.get("avoid")
        if avoid is not None and not isinstance(avoid, list):
            raise ValueError("'avoid' must be a list of [src, dst] pairs")
        objective = data.get("objective", "latency")
        include_down = bool(data.get("include_down", False))

        avoid_pairs: List[Tuple[str, str]] | None = None
        if avoid:
            avoid_pairs = []
            for edge in avoid:
                if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                    raise ValueError("Each avoid entry must be [src, dst]")
                avoid_pairs.append((edge[0], edge[1]))

        result = self.compute_shortest_path(
            src,
            dst,
            avoid=avoid_pairs,
            objective=objective,
            include_down=include_down,
        )
        result.update({
            "tool": "compute_resilient_path",
            "link": [src, dst],
        })
        return json.dumps(result)

    @staticmethod
    def _loads(payload: str) -> Dict[str, Any]:
        if not payload:
            return {}
        return json.loads(payload)


SYSTEM_PROMPT = (
    "You are a senior network reliability LLM operating a Mininet data center lab.\n"
    "Follow the ReAct loop strictly: observe with tools before taking actions.\n"
    "All tool inputs must be JSON objects.\n"
    "Use monitor_link and inspect_link_health to gather live utilisation, throughput, and latency before\n"
    "modifying the network.\n"
    "When a failure is detected, activate backup paths or call compute_resilient_path to identify alternatives,\n"
    "then monitor until the primary link is healthy and restore it.\n"
    "Respond with `Final Answer: <summary>` once mitigation and validation are complete.\n"
    "\n"
    "Available tools:\n{tools}\n"
    "Select from these tool names exactly: {tool_names}."
)


def build_mininet_agent(llm: BaseLanguageModel, env: DataCenterEnvironment):
    tools = [
        Tool(
            name="get_topology_snapshot",
            description="Return the complete blueprint metadata and current link state.",
            func=lambda _: json.dumps(env.snapshot()),
        ),
        Tool(
            name="monitor_link",
            description="Monitor utilisation and status of a link. Input JSON with src/dst.",
            func=env.monitor_link,
        ),
        Tool(
            name="inspect_link_health",
            description="Detailed health metrics for a link. JSON: {src,dst}.",
            func=env.inspect_link_health,
        ),
        Tool(
            name="probe_connectivity",
            description="Ping between hosts. Input JSON with src, dst, optional count.",
            func=env.probe_connectivity,
        ),
        Tool(
            name="traceroute",
            description="Run traceroute between hosts. Input JSON with src and dst.",
            func=env.traceroute,
        ),
        Tool(
            name="simulate_failure",
            description="Apply a failure mode to a link. JSON: {src,dst,mode,severity}.",
            func=env.simulate_failure,
        ),
        Tool(
            name="activate_backup_path",
            description="Bring a backup path online. JSON: {path: [n1,n2,...]}.",
            func=env.activate_backup_path,
        ),
        Tool(
            name="restore_primary_path",
            description="Reapply baseline profile once healthy. JSON with src/dst.",
            func=env.restore_primary_path,
        ),
        Tool(
            name="compute_resilient_path",
            description="Compute alternate path between two nodes. JSON: {src,dst,objective?,avoid?}.",
            func=env.compute_resilient_path,
        ),
    ]

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


class MininetAgentConfig(BaseModel):
    model: str = Field(
        default_factory=lambda: os.getenv(
            "GEN_ENGINE_MODEL", "anthropic.claude-3-5-sonnet-20240620-v1:0"
        )
    )
    api_base: str | None = Field(default_factory=lambda: os.getenv("REST_API_BASE"))
    api_key: str | None = Field(default_factory=lambda: os.getenv("API_KEY"))
    temperature: float = 0.0
    max_tokens: int = 2048


def load_mininet_llm(config: MininetAgentConfig | None = None) -> GenerativeEngineLLM:
    cfg = config or MininetAgentConfig()
    if cfg.api_base is None or cfg.api_key is None:
        raise RuntimeError(
            "REST_API_BASE and API_KEY environment variables are required to initialise the Generative Engine LLM."
        )
    return GenerativeEngineLLM(
        model=cfg.model,
        api_base=cfg.api_base,
        api_key=cfg.api_key,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
    )


@dataclass(slots=True)
class MininetAgentScenario:
    env: DataCenterEnvironment
    llm: BaseLanguageModel
    investigation_prompt: str = (
        "We detected loss between tenant web frontends and the database tier. Diagnose the failure, "
        "activate a resilient path, then restore the primary design once healthy."
    )

    def run(self) -> Dict[str, Any]:
        agent = build_mininet_agent(self.llm, self.env)
        logger.info("Executing Mininet remediation scenario")
        return agent.invoke({"input": self.investigation_prompt})


def run_demo(blueprint_path: str | None = None) -> None:  # pragma: no cover
    env = DataCenterEnvironment()
    if blueprint_path:
        logger.info("Loading topology from %s", blueprint_path)
        env = DataCenterEnvironment.load_state(blueprint_path)
    try:
        env.start()
        env.simulate_failure(json.dumps({"src": "core1", "dst": "agg1a", "mode": "cable_cut"}))
        env.activate_backup_path(json.dumps({"path": ["core2", "agg2a"]}))
        llm = load_mininet_llm()
        scenario = MininetAgentScenario(env=env, llm=llm)
        outcome = scenario.run()
        print("\nAgent Outcome\n------------")
        print(outcome.get("output"))
        export_path = env.save_state("topology_snapshot.json")
        print(f"\nState exported to {export_path}")
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        env.stop()


if __name__ == "__main__":  # pragma: no cover
    run_demo()
