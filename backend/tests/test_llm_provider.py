from app.core.config import Settings
from app.providers.llm.router import build_provider


def test_build_provider_uses_nvidia_provider(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: Settings(llm_provider="nvidia", nvidia_api_key="test-key"),
    )

    provider = build_provider()

    assert provider.__class__.__name__ == "NvidiaProvider"
    assert provider._client.api_key == "test-key"
    assert str(provider._client.base_url).rstrip("/") == "https://integrate.api.nvidia.com/v1"


def test_default_nvidia_models_are_supported():
    settings = Settings()

    assert settings.model_extract == "meta/llama-3.2-11b-vision-instruct"
    assert settings.model_reason == "meta/llama-3.2-11b-vision-instruct"
    assert settings.model_judge == "meta/llama-3.2-11b-vision-instruct"
