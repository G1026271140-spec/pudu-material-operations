import app
import backend_runtime as runtime
import pytest


def test_environment_overrides_file(tmp_path, monkeypatch):
    path = tmp_path / 'secrets.toml'
    path.write_text('EXAMPLE_SECRET="file-value"', encoding='utf-8')
    monkeypatch.setenv('PUDU_SECRETS_FILE', str(path))
    monkeypatch.setenv('EXAMPLE_SECRET', 'environment-value')
    assert app.get_secret_value('EXAMPLE_SECRET') == 'environment-value'


def test_file_without_environment(tmp_path, monkeypatch):
    path = tmp_path / 'secrets.toml'
    path.write_text('EXAMPLE_SECRET="file-value"', encoding='utf-8')
    monkeypatch.setenv('PUDU_SECRETS_FILE', str(path))
    monkeypatch.delenv('EXAMPLE_SECRET', raising=False)
    assert app.get_secret_value('EXAMPLE_SECRET') == 'file-value'


def test_default_without_file(tmp_path, monkeypatch):
    monkeypatch.setenv('PUDU_SECRETS_FILE', str(tmp_path / 'absent.toml'))
    monkeypatch.delenv('EXAMPLE_SECRET', raising=False)
    assert app.get_secret_value('EXAMPLE_SECRET', 'fallback') == 'fallback'


def test_malformed_file_does_not_silently_use_default(tmp_path, monkeypatch):
    path=tmp_path/'secrets.toml';path.write_text('INVALID=[', encoding='utf-8')
    monkeypatch.setenv('PUDU_SECRETS_FILE',str(path))
    with pytest.raises(ValueError): runtime.secret('EXAMPLE_SECRET')
