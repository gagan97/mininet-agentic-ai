import pytest

from gen_engine_deep_eval.datacenter_agent import (
    SYSTEM_PROMPT,
    MininetAgentConfig,
    MininetAgentScenario,
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
