"""Read-only cutover preflight must not modify config or expose secrets."""

from scripts.kta99_openai_preflight import inspect


def _config(tmp_path):
    file = tmp_path / "config.yaml"
    file.write_text(
        "model:\n  provider: deepseek\n  default: deepseek-v4-pro\n"
        "gateway:\n  enabled: true\n",
        encoding="utf-8",
    )
    return file


def test_ready_with_configured_key_and_unchanged_config(tmp_path):
    file = _config(tmp_path)
    before = file.read_bytes()
    result = inspect(file, {"OPENAI_API_KEY": "sk-test"}, probe=False)
    assert result["ready_for_cutover"] is True
    assert result["current_provider"] == "deepseek"
    assert result["current_model"] == "deepseek-v4-pro"
    assert "sk-test" not in repr(result)
    assert file.read_bytes() == before


def test_missing_api_key_fails_closed(tmp_path):
    result = inspect(_config(tmp_path), {})
    assert result["openai_key_configured"] is False
    assert result["ready_for_cutover"] is False


def test_unsafe_override_fails_closed(tmp_path):
    result = inspect(
        _config(tmp_path),
        {
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "https://api.openai.com.evil.example/v1",
        },
    )
    assert result["openai_endpoint_safe"] is False
    assert result["ready_for_cutover"] is False


def test_missing_config_fails_closed(tmp_path):
    result = inspect(tmp_path / "not_found.yaml", {"OPENAI_API_KEY": "sk-test"})
    assert result["config_readable"] is False
    assert result["ready_for_cutover"] is False


def test_yaml_scalar_fails_closed(tmp_path):
    file = tmp_path / "config.yaml"
    file.write_text("hello\n", encoding="utf-8")
    result = inspect(file, {"OPENAI_API_KEY": "sk-test"})
    assert result["ready_for_cutover"] is False
