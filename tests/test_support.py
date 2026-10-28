from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.support import load_api_key, redact


@pytest.mark.parametrize(
    "contents",
    [
        'ANYSEARCH_API_KEY="file-key"\n',
        '\ufeffexport ANYSEARCH_API_KEY="file-key" # comment\n',
        "# comment\nANYSEARCH_API_KEY='file-key'\n",
    ],
)
def test_api_key_loading_uses_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str
) -> None:
    monkeypatch.delenv("ANYSEARCH_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text(contents)
    key = load_api_key(path)
    assert key is not None
    assert key.get_secret_value() == "file-key"
    assert "file-key" not in repr(key)
    monkeypatch.setenv("ANYSEARCH_API_KEY", " environment-key ")
    assert load_api_key(path) == SecretStr("environment-key")
    monkeypatch.setenv("ANYSEARCH_API_KEY", " ")
    assert load_api_key(path) == SecretStr("file-key")


@pytest.mark.parametrize(
    "contents", ["", "ANYSEARCH_API_KEY=", "ANYSEARCH_API_KEY=' '"]
)
def test_missing_api_key_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str
) -> None:
    monkeypatch.delenv("ANYSEARCH_API_KEY", raising=False)
    path = tmp_path / ".env"
    assert load_api_key(path) is None
    path.write_text(contents)
    assert load_api_key(path) is None


def test_credentials_are_redacted_from_live_failure_reports() -> None:
    text = (
        "Authorization: Bearer secret-key\napi_key=generated-key\n"
        "password=generated-password\nusername=generated-user\nrequest_id=keep-this"
    )
    result = redact(text, SecretStr("secret-key"))
    assert all(
        secret not in result
        for secret in (
            "secret-key",
            "generated-key",
            "generated-password",
            "generated-user",
        )
    )
    assert "request_id=keep-this" in result
