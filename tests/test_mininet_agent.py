import json

import pytest

from gen_engine_deep_eval.datacenter_agent import (
    SYSTEM_PROMPT,
    DataCenterEnvironment,
    LinkProfile,
    LinkSpec,
    MininetAgentConfig,
    MininetAgentScenario,
    NodeSpec,
    TopologyBlueprint,
    build_datacenter_blueprint,
    load_mininet_llm,
)


def test_system_prompt_mentions_final_answer():
    assert "Final Answer" in SYSTEM_PROMPT


def test_config_respects_environment(monkeypatch):
    monkeypatch.setenv("GEN_ENGINE_MODEL", "demo-model")
    cfg = MininetAgentConfig()
    assert cfg.model == "demo-model"


def test_load_mininet_llm_requires_credentials(monkeypatch):
    monkeypatch.delenv("REST_API_BASE", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    cfg = MininetAgentConfig(api_base=None, api_key=None)
    with pytest.raises(RuntimeError):
        load_mininet_llm(cfg)


def test_scenario_uses_default_prompt():
    scenario = MininetAgentScenario(env=None, llm=None)  # type: ignore[arg-type]
    assert "failure" in scenario.investigation_prompt.lower()
    # Ensure dataclass stores supplied env/llm for later wiring
    assert scenario.env is None
    assert scenario.llm is None


def test_blueprint_serialisation_roundtrip(tmp_path):
    blueprint = build_datacenter_blueprint()
    snapshot = blueprint.to_dict()
    restored = TopologyBlueprint.from_dict(snapshot)
    assert restored.name == blueprint.name
    assert len(restored.nodes) == len(blueprint.nodes)
    assert len(restored.links) == len(blueprint.links)


def _fake_mininet_imports():
    class DummyMininet:  # pragma: no cover - simple stub
        pass

    return DummyMininet, DummyMininet, DummyMininet, DummyMininet, DummyMininet


def _seed_profiles(env: DataCenterEnvironment) -> None:
    env.link_profiles = {}
    for link in env.blueprint.links:
        env.link_profiles[link.key()] = LinkProfile(
            bw_gbps=link.port_speed_gbps,
            delay_ms=link.delay_ms,
            loss_percent=link.loss_percent,
        )


def test_topology_graph_respects_link_status(monkeypatch):
    monkeypatch.setattr("gen_engine_deep_eval.datacenter_agent._ensure_mininet_imports", _fake_mininet_imports)
    env = DataCenterEnvironment()
    _seed_profiles(env)

    graph_up = env._get_topology_graph()
    assert graph_up.has_edge("core1", "agg1a")

    key = env._link_key("core1", "agg1a")
    env.link_profiles[key].status = "down"
    env._topology_graph = None

    graph_filtered = env._get_topology_graph()
    assert ("core1", "agg1a") not in graph_filtered.edges()

    graph_all = env._get_topology_graph(include_down=True)
    assert graph_all.has_edge("core1", "agg1a")
    data = graph_all["core1"]["agg1a"]
    assert data.get("status") == "down"


def test_compute_shortest_path_by_latency(monkeypatch):
    monkeypatch.setattr("gen_engine_deep_eval.datacenter_agent._ensure_mininet_imports", _fake_mininet_imports)
    blueprint = TopologyBlueprint(
        name="triangle",
        nodes=[
            NodeSpec("a", role="core", model="core", node_type="switch"),
            NodeSpec("b", role="aggregation", model="agg", node_type="switch"),
            NodeSpec("c", role="aggregation", model="agg", node_type="switch"),
        ],
        links=[
            LinkSpec("a", "b", link_type="core-aggregation", port_speed_gbps=10, delay_ms=2, loss_percent=0.0),
            LinkSpec("b", "c", link_type="aggregation-aggregation", port_speed_gbps=10, delay_ms=2, loss_percent=0.0),
            LinkSpec("a", "c", link_type="core-aggregation", port_speed_gbps=10, delay_ms=20, loss_percent=0.0),
        ],
    )

    env = DataCenterEnvironment(blueprint=blueprint)
    _seed_profiles(env)

    # Inflate direct link latency to force a-b-c selection
    direct_key = env._link_key("a", "c")
    env.link_profiles[direct_key].delay_ms = 50
    env._topology_graph = None

    result = env.compute_shortest_path("a", "c")
    assert result["path"] == ["a", "b", "c"]
    assert result["objective"] == "latency"
    assert result["total_latency_ms"] >= 4

    # Capacity objective should prefer the direct link when we reduce its utilisation
    env.link_profiles[direct_key].delay_ms = 5
    env.link_profiles[direct_key].throughput_gbps = 1.0
    env.link_profiles[direct_key].utilisation_percent = 10.0
    ab_key = env._link_key("a", "b")
    bc_key = env._link_key("b", "c")
    env.link_profiles[ab_key].throughput_gbps = 9.5
    env.link_profiles[bc_key].throughput_gbps = 9.5
    env.link_profiles[ab_key].utilisation_percent = 95.0
    env.link_profiles[bc_key].utilisation_percent = 95.0
    env._topology_graph = None

    result_capacity = env.compute_shortest_path("a", "c", objective="capacity")
    assert result_capacity["path"] == ["a", "c"]


def test_compute_shortest_path_avoids_edges(monkeypatch):
    monkeypatch.setattr("gen_engine_deep_eval.datacenter_agent._ensure_mininet_imports", _fake_mininet_imports)
    blueprint = TopologyBlueprint(
        name="square",
        nodes=[
            NodeSpec("n1", role="core", model="core", node_type="switch"),
            NodeSpec("n2", role="aggregation", model="agg", node_type="switch"),
            NodeSpec("n3", role="aggregation", model="agg", node_type="switch"),
            NodeSpec("n4", role="access", model="acc", node_type="switch"),
        ],
        links=[
            LinkSpec("n1", "n2", link_type="core-aggregation", port_speed_gbps=10, delay_ms=1, loss_percent=0.0),
            LinkSpec("n2", "n4", link_type="aggregation-access", port_speed_gbps=10, delay_ms=1, loss_percent=0.0),
            LinkSpec("n1", "n3", link_type="core-aggregation", port_speed_gbps=10, delay_ms=1, loss_percent=0.0),
            LinkSpec("n3", "n4", link_type="aggregation-access", port_speed_gbps=10, delay_ms=1, loss_percent=0.0),
        ],
    )

    env = DataCenterEnvironment(blueprint=blueprint)
    _seed_profiles(env)

    result_default = env.compute_shortest_path("n1", "n4")
    assert result_default["path"] in (["n1", "n2", "n4"], ["n1", "n3", "n4"])

    result_avoid = env.compute_shortest_path("n1", "n4", avoid=[("n1", "n2")])
    assert result_avoid["path"] == ["n1", "n3", "n4"]


def test_inspect_link_health_returns_profile(monkeypatch):
    monkeypatch.setattr("gen_engine_deep_eval.datacenter_agent._ensure_mininet_imports", _fake_mininet_imports)
    env = DataCenterEnvironment()
    _seed_profiles(env)

    output = env.inspect_link_health(json.dumps({"src": "core1", "dst": "agg1a"}))
    payload = json.loads(output)
    assert payload["tool"] == "inspect_link_health"
    assert payload["link"] == ["core1", "agg1a"]
    assert "profile" in payload


def test_monitor_link_unknown_returns_error(monkeypatch):
    monkeypatch.setattr("gen_engine_deep_eval.datacenter_agent._ensure_mininet_imports", _fake_mininet_imports)
    env = DataCenterEnvironment()
    _seed_profiles(env)

    response = env.monitor_link(json.dumps({"src": "acc11a", "dst": "acc21a"}))
    payload = json.loads(response)
    assert payload["tool"] == "monitor_link"
    assert payload["link"] == ["acc11a", "acc21a"]
    assert payload["error"].startswith("unknown link")
    assert payload.get("suggestions")


def test_compute_resilient_path_tool(monkeypatch):
    monkeypatch.setattr("gen_engine_deep_eval.datacenter_agent._ensure_mininet_imports", _fake_mininet_imports)
    env = DataCenterEnvironment()
    _seed_profiles(env)

    response = env.compute_resilient_path(json.dumps({"src": "core1", "dst": "agg1b"}))
    payload = json.loads(response)
    assert payload["tool"] == "compute_resilient_path"
    assert payload["path"][0] == "core1"
    assert payload["link"] == ["core1", "agg1b"]


def test_compute_resilient_path_accepts_string_avoid(monkeypatch):
    monkeypatch.setattr("gen_engine_deep_eval.datacenter_agent._ensure_mininet_imports", _fake_mininet_imports)
    blueprint = TopologyBlueprint(
        name="triangle",
        nodes=[
            NodeSpec("a", role="core", model="core", node_type="switch"),
            NodeSpec("b", role="aggregation", model="agg", node_type="switch"),
            NodeSpec("c", role="aggregation", model="agg", node_type="switch"),
        ],
        links=[
            LinkSpec("a", "b", link_type="core-aggregation", port_speed_gbps=10, delay_ms=1, loss_percent=0.0),
            LinkSpec("b", "c", link_type="aggregation-aggregation", port_speed_gbps=10, delay_ms=1, loss_percent=0.0),
            LinkSpec("a", "c", link_type="core-aggregation", port_speed_gbps=10, delay_ms=1, loss_percent=0.0),
        ],
    )

    env = DataCenterEnvironment(blueprint=blueprint)
    _seed_profiles(env)

    response = env.compute_resilient_path(
        json.dumps({"src": "a", "dst": "c", "avoid": ["a-c"]})
    )
    payload = json.loads(response)
    assert payload["tool"] == "compute_resilient_path"
    assert payload["path"] == ["a", "b", "c"]
