from src import paths
from src.api.settings import ApiSettings


def test_relative_state_settings_are_relative_to_project_not_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ADVISOR_REQUEST_STORE_PATH", ".api-state/test.sqlite3")
    monkeypatch.setenv("ADVISOR_HISTORY_INCREMENTAL_ROOT", "data/artifacts/test_updates")
    monkeypatch.setenv("ADVISOR_HISTORY_BASELINE_SOURCE_ROOT", "data/artifacts/history")
    settings = ApiSettings.from_env()
    assert settings.request_store_path == paths.PROJECT_ROOT / ".api-state/test.sqlite3"
    assert settings.incremental_history_root == paths.PROJECT_ROOT / "data/artifacts/test_updates"
    assert settings.history_baseline_source_root == paths.PROJECT_ROOT / "data/artifacts/history"
