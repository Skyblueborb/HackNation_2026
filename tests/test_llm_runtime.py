import pytest

from lab.llm.config import load_models
from lab.paths import REPO_ROOT
from local_ai.llm import build_local_config


def test_llm_has_gpu_and_local_profiles():
    models = load_models(REPO_ROOT / "configs" / "models.yaml")
    assert "-ngl 99" in models["qwen3-8b-l4"].server_flags
    assert "-fa on" in models["qwen3-8b-l4"].server_flags
    assert "-ngl 99" in models["local-llm"].server_flags
    assert models["local-llm"].hf_repo


def test_build_local_config_defaults_to_local_profile():
    config = build_local_config()
    assert config.id == "local-llm"
    assert config.port == 8081
    assert config.base_url == "http://localhost:8081/v1"
    assert "-ngl 99" in config.server_flags


def test_build_local_config_cpu_keeps_other_flags():
    default = build_local_config()
    config = build_local_config(cpu=True)

    assert "-ngl 0" in config.server_flags
    assert "-ngl 99" not in config.server_flags
    # --cpu may swap the -ngl flag and nothing else. Comparing against the
    # profile instead of literal flag values keeps this test honest when
    # models.yaml tunes the context size, which has already happened twice.
    assert config.server_flags == default.server_flags.replace("-ngl 99", "-ngl 0")


def test_build_local_config_port_overrides_url():
    config = build_local_config(port=9090)
    assert config.port == 9090
    assert config.base_url == "http://localhost:9090/v1"


def test_build_local_config_unknown_model_raises():
    with pytest.raises(ValueError, match="unknown model"):
        build_local_config("nope")
