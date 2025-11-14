"""GUI Topology Adapter - Transform GUI REST API data to TopologyBlueprint.

This module provides a clean adapter layer that fetches topology data from the
GUI simulation tool's REST API and transforms it into the datacenter agent's
internal TopologyBlueprint and LinkProfile formats.

Key responsibilities:
* Fetch topology from GUI /api/network/topology endpoint
* Transform switches, connections, and hosts to NodeSpec/LinkSpec
* Calculate derived metrics (link delays, link types)
* Detect active failures from connection and port status
* Generate LinkProfile dictionaries with current utilization

Usage:
    adapter = GUITopologyAdapter("http://localhost:5000")
    blueprint = adapter.fetch_and_transform()
    failures = adapter.detect_failures()
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import requests
from loguru import logger

from .datacenter_agent import (
    LinkProfile,
    LinkSpec,
    LinkType,
    NodeRole,
    NodeSpec,
    TopologyBlueprint,
)


class GUITopologyAdapter:
    """Adapter to convert GUI simulation tool topology to agent format."""

    def __init__(self, gui_base_url: str):
        """Initialize adapter with GUI base URL.

        Args:
            gui_base_url: Base URL of GUI API (e.g., "http://localhost:5000")
        """
        self.base_url = gui_base_url.rstrip("/")
        self._raw_topology: Dict[str, Any] | None = None

    def fetch_topology(self) -> Dict[str, Any]:
        """Fetch current topology from GUI API.

        Returns:
            Raw topology data from GUI API

        Raises:
            requests.RequestException: If API call fails
        """
        url = f"{self.base_url}/api/network/topology"
        logger.info(f"Fetching topology from {url}")

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if not data.get("success", False):
                raise ValueError(f"API returned error: {data.get('message')}")

            self._raw_topology = data["data"]
            logger.info(
                f"Fetched topology: {len(self._raw_topology['switches'])} switches, "
                f"{len(self._raw_topology['connections'])} connections"
            )
            return self._raw_topology

        except requests.RequestException as e:
            logger.error(f"Failed to fetch topology from GUI: {e}")
            raise

    def to_blueprint(self, gui_topology: Dict[str, Any] | None = None) -> TopologyBlueprint:
        """Transform GUI topology to TopologyBlueprint.

        Args:
            gui_topology: Optional raw GUI topology data. If None, uses cached data.

        Returns:
            TopologyBlueprint with nodes and links
        """
        if gui_topology is None:
            if self._raw_topology is None:
                raise ValueError("No topology data available. Call fetch_topology() first.")
            gui_topology = self._raw_topology

        nodes: List[NodeSpec] = []

        # Convert switches to NodeSpec
        for switch in gui_topology.get("switches", []):
            role = self._map_switch_role(switch["type"])
            max_capacity = self._max_port_capacity(switch.get("ports", []))

            nodes.append(
                NodeSpec(
                    name=switch["id"],
                    role=role,
                    model=switch.get("model", "Unknown"),
                    node_type="switch",
                    port_speed_gbps=max_capacity,
                    metadata={
                        "location": switch.get("location", ""),
                        "mgmt_ip": switch.get("managementIp", ""),
                        "cpu_percent": switch.get("cpu", 0),
                        "memory_percent": switch.get("memory", 0),
                        "temperature_c": switch.get("temperature", 0),
                        "display_name": switch.get("name", switch["id"]),
                    },
                )
            )

        # Convert hosts to NodeSpec
        for host in gui_topology.get("hosts", []):
            nodes.append(
                NodeSpec(
                    name=host["id"],
                    role="host",
                    model=host.get("type", "server"),
                    node_type="host",
                    port_speed_gbps=None,
                    metadata={
                        "ip": host.get("ip", ""),
                        "mac": host.get("mac", ""),
                        "services": host.get("services", []),
                        "vlan": host.get("vlan", ""),
                        "switch_id": host.get("switchId", ""),
                        "port_number": host.get("portNumber", 0),
                        "display_name": host.get("name", host["id"]),
                    },
                )
            )

        # Convert connections to LinkSpec
        links: List[LinkSpec] = []
        for conn in gui_topology.get("connections", []):
            src_switch = conn["sourceSwitch"]
            dst_switch = conn["targetSwitch"]

            # Get link type from switch types
            link_type = self._infer_link_type(gui_topology, src_switch, dst_switch)

            # Get port capacity
            port_capacity = self._get_port_capacity(
                gui_topology, src_switch, conn["sourcePort"]
            )

            # Calculate delay from cable length
            delay_ms = self._calculate_delay(
                conn.get("cableLength", "10m"), conn.get("cableType", "fiber")
            )

            links.append(
                LinkSpec(
                    src=src_switch,
                    dst=dst_switch,
                    link_type=link_type,
                    port_speed_gbps=port_capacity,
                    medium="fiber" if conn.get("cableType") == "fiber" else "copper",
                    delay_ms=delay_ms,
                    loss_percent=0.0,
                    description=(
                        f"{src_switch}:{conn['sourcePort']} → "
                        f"{dst_switch}:{conn['targetPort']}"
                    ),
                )
            )

        blueprint = TopologyBlueprint(
            name="gui-imported-topology", nodes=nodes, links=links
        )

        logger.info(
            f"Created blueprint: {len(nodes)} nodes ({len([n for n in nodes if n.node_type == 'switch'])} switches, "
            f"{len([n for n in nodes if n.node_type == 'host'])} hosts), {len(links)} links"
        )

        return blueprint

    def get_link_profiles(
        self, gui_topology: Dict[str, Any] | None = None
    ) -> Dict[Tuple[str, str], LinkProfile]:
        """Extract current link states and utilization from GUI topology.

        Args:
            gui_topology: Optional raw GUI topology data. If None, uses cached data.

        Returns:
            Dictionary mapping (src, dst) tuples to LinkProfile
        """
        if gui_topology is None:
            if self._raw_topology is None:
                raise ValueError("No topology data available. Call fetch_topology() first.")
            gui_topology = self._raw_topology

        profiles: Dict[Tuple[str, str], LinkProfile] = {}

        for conn in gui_topology.get("connections", []):
            src_switch = conn["sourceSwitch"]
            dst_switch = conn["targetSwitch"]

            # Find source port to get utilization
            src_port = self._find_port(gui_topology, src_switch, conn["sourcePort"])

            if not src_port:
                logger.warning(
                    f"Could not find port {conn['sourcePort']} on {src_switch}"
                )
                continue

            # Create key (sorted for bidirectional lookup)
            key = tuple(sorted([src_switch, dst_switch]))

            # Determine link status
            conn_active = conn.get("status") == "active"
            port_connected = src_port.get("status") == "CONNECTED"
            status = "up" if (conn_active and port_connected) else "down"

            # Calculate delay
            delay_ms = self._calculate_delay(
                conn.get("cableLength", "10m"), conn.get("cableType", "fiber")
            )

            profiles[key] = LinkProfile(
                bw_gbps=src_port.get("capacityGbps", 10.0),
                delay_ms=delay_ms,
                loss_percent=0.0 if status == "up" else 100.0,
                utilisation_percent=src_port.get("utilization", 0.0),
                status=status,
                throughput_gbps=None,
                observed_rtt_ms=None,
                last_sample_timestamp=None,
            )

        logger.info(f"Created {len(profiles)} link profiles")
        return profiles

    def detect_failures(
        self, gui_topology: Dict[str, Any] | None = None
    ) -> List[Dict[str, Any]]:
        """Detect active failures from GUI topology state.

        Args:
            gui_topology: Optional raw GUI topology data. If None, uses cached data.

        Returns:
            List of failure dictionaries with type, location, and severity
        """
        if gui_topology is None:
            if self._raw_topology is None:
                raise ValueError("No topology data available. Call fetch_topology() first.")
            gui_topology = self._raw_topology

        failures: List[Dict[str, Any]] = []

        # Check for inactive connections
        for conn in gui_topology.get("connections", []):
            if conn.get("status") == "inactive":
                failures.append(
                    {
                        "type": "connection_down",
                        "link": (conn["sourceSwitch"], conn["targetSwitch"]),
                        "ports": (conn["sourcePort"], conn["targetPort"]),
                        "detected_from": "connection.status",
                        "severity": "CRITICAL",
                        "connection_id": conn.get("id", "unknown"),
                    }
                )

        # Check for port status issues
        for switch in gui_topology.get("switches", []):
            for port in switch.get("ports", []):
                status = port.get("status", "CONNECTED")
                if status in ("PLUGGED_OUT", "CABLE_CUT", "TRAFFIC_DROP"):
                    severity = "CRITICAL" if "CUT" in status else "WARNING"

                    failures.append(
                        {
                            "type": status.lower(),
                            "switch": switch["id"],
                            "switch_name": switch.get("name", switch["id"]),
                            "port": port["portNumber"],
                            "port_id": port.get("id", "unknown"),
                            "severity": severity,
                            "detected_from": "port.status",
                        }
                    )

        # Check for SFP mismatches
        for switch in gui_topology.get("switches", []):
            for port in switch.get("ports", []):
                if port.get("sfpStatus") == "mismatch":
                    failures.append(
                        {
                            "type": "sfp_mismatch",
                            "switch": switch["id"],
                            "switch_name": switch.get("name", switch["id"]),
                            "port": port["portNumber"],
                            "current_sfp": port.get("sfpType", "unknown"),
                            "required_sfp": port.get("requiredSfpType", "unknown"),
                            "severity": "ERROR",
                            "detected_from": "port.sfpStatus",
                        }
                    )

        logger.info(f"Detected {len(failures)} failures")
        return failures

    def fetch_and_transform(self) -> Tuple[TopologyBlueprint, Dict[Tuple[str, str], LinkProfile]]:
        """Convenience method to fetch and transform in one call.

        Returns:
            Tuple of (TopologyBlueprint, link_profiles dict)
        """
        topology = self.fetch_topology()
        blueprint = self.to_blueprint(topology)
        profiles = self.get_link_profiles(topology)
        return blueprint, profiles

    # Helper methods

    def _map_switch_role(self, switch_type: str) -> NodeRole:
        """Map GUI switch type to agent NodeRole."""
        type_lower = switch_type.lower()
        if type_lower in ("core", "edge"):
            return "core"
        elif type_lower == "aggregation":
            return "aggregation"
        elif type_lower == "access":
            return "access"
        else:
            logger.warning(f"Unknown switch type '{switch_type}', defaulting to 'access'")
            return "access"

    def _max_port_capacity(self, ports: List[Dict]) -> float:
        """Get maximum port capacity from port list."""
        if not ports:
            return 10.0  # Default to 10 Gbps

        capacities = [p.get("capacityGbps", 1.0) for p in ports]
        return max(capacities)

    def _infer_link_type(
        self, gui_topology: Dict, src_switch: str, dst_switch: str
    ) -> LinkType:
        """Infer link type from source and destination switch types."""
        src_type = self._get_switch_type(gui_topology, src_switch)
        dst_type = self._get_switch_type(gui_topology, dst_switch)

        # Create sorted tuple for consistent lookup
        types = tuple(sorted([src_type.lower(), dst_type.lower()]))

        # Map type pairs to LinkType
        type_map = {
            ("aggregation", "core"): "core-aggregation",
            ("core", "edge"): "core-aggregation",  # edge treated as core
            ("access", "aggregation"): "aggregation-access",
            ("aggregation", "aggregation"): "aggregation-aggregation",
            ("access", "access"): "access-access",
        }

        result = type_map.get(types)
        if result:
            return result

        # Check if one is a host (not in switches)
        if src_type == "host" or dst_type == "host":
            return "access-host"

        # Default fallback
        logger.warning(
            f"Could not determine link type for {src_switch}({src_type}) - "
            f"{dst_switch}({dst_type}), defaulting to aggregation-access"
        )
        return "aggregation-access"

    def _get_switch_type(self, gui_topology: Dict, switch_id: str) -> str:
        """Get switch type by ID."""
        for switch in gui_topology.get("switches", []):
            if switch["id"] == switch_id:
                return switch.get("type", "access")

        # Not found in switches, might be a host
        for host in gui_topology.get("hosts", []):
            if host["id"] == switch_id:
                return "host"

        return "unknown"

    def _get_port_capacity(
        self, gui_topology: Dict, switch_id: str, port_number: int
    ) -> float:
        """Get port capacity in Gbps."""
        port = self._find_port(gui_topology, switch_id, port_number)
        if port:
            return port.get("capacityGbps", 10.0)
        return 10.0  # Default

    def _find_port(
        self, gui_topology: Dict, switch_id: str, port_number: int
    ) -> Dict[str, Any] | None:
        """Find port by switch ID and port number."""
        for switch in gui_topology.get("switches", []):
            if switch["id"] == switch_id:
                for port in switch.get("ports", []):
                    if port.get("portNumber") == port_number:
                        return port
        return None

    def _calculate_delay(self, cable_length: str, cable_type: str) -> int:
        """Calculate link delay from cable length and type.

        Assumes:
        - Fiber: ~5 ns/m (200,000 km/s in fiber)
        - Copper: ~4.9 ns/m (204,000 km/s in copper)
        - Switch processing: 2ms base delay

        Args:
            cable_length: String like "15m", "0.5km"
            cable_type: "fiber" or "copper"

        Returns:
            Delay in milliseconds
        """
        # Parse length
        match = re.match(r"([\d.]+)\s*([kmKM]?)[mM]?", cable_length)
        if not match:
            logger.warning(f"Could not parse cable length '{cable_length}', using 10m")
            length_m = 10.0
        else:
            value = float(match.group(1))
            unit = match.group(2).lower() if match.group(2) else ""
            length_m = value * 1000 if unit == "k" else value

        # Calculate propagation delay
        ns_per_m = 5.0 if cable_type == "fiber" else 4.9
        propagation_ms = (length_m * ns_per_m) / 1_000_000

        # Add switching delay
        switch_delay_ms = 2.0

        total_delay = int(propagation_ms + switch_delay_ms)
        return max(total_delay, 1)  # At least 1ms
