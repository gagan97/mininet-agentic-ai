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
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple

from langchain.agents import AgentType, Tool, initialize_agent
from langchain_core.language_models import BaseLanguageModel
from loguru import logger
from pydantic.v1 import BaseModel, Field

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
        payload = {
            "tool": "monitor_link",
            "link": [src, dst],
            "status": profile.status,
            "bw_gbps": profile.bw_gbps,
            "delay_ms": profile.delay_ms,
            "loss_percent": profile.loss_percent,
            "utilisation_percent": round(profile.utilisation_percent, 2),
            "within_baseline": profile.utilisation_percent < 70,
        }
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
        return json.dumps({"tool": "restore_primary_path", "link": [src, dst], "profile": baseline.to_dict()})

    def _set_link_state(self, src: str, dst: str, state: Literal["up", "down"]) -> None:
        if self.net is None:
            return
        logger.info("Setting link %s-%s -> %s", src, dst, state)
        self.net.configLinkStatus(src, dst, state)

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
            links = self.net.linksBetween(src, dst)
            if not links:
                raise ValueError(f"No Mininet link between {src} and {dst}")
            link = links[0]
            for intf in (link.intf1, link.intf2):
                intf.config(**updates)
        if status is not None:
            self._set_link_state(src, dst, status)

    @staticmethod
    def _link_key(src: str, dst: str) -> Tuple[str, str]:
        return tuple(sorted((src, dst)))

    @staticmethod
    def _loads(payload: str) -> Dict[str, Any]:
        if not payload:
            return {}
        return json.loads(payload)


SYSTEM_PROMPT = (
    "You are a senior network reliability LLM operating a Mininet data center lab.\n"
    "Follow the ReAct loop strictly: observe with tools before taking actions.\n"
    "All tool inputs must be JSON objects.\n"
    "When a failure is detected, activate backup paths to preserve service, then monitor until\n"
    "the primary link is healthy and restore it.\n"
    "Respond with `Final Answer: <summary>` once mitigation and validation are complete."
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
    ]

    return initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True,
        agent_kwargs={"system_message": SYSTEM_PROMPT},
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
    finally:
        env.stop()


if __name__ == "__main__":  # pragma: no cover
    run_demo()
