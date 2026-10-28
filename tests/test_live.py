from __future__ import annotations

import os
from pathlib import Path

import pytest

from anysearch_py import Client, Domain, MCPClient

ENV_FILE = Path(".env")


def load_api_key() -> str:
    api_key = os.getenv("ANYSEARCH_API_KEY", "").strip()
    if api_key:
        return api_key

    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, _, value = stripped.partition("=")
            api_key = value.strip().strip("\"'").strip()
            if key.strip().lstrip("\ufeff") == "ANYSEARCH_API_KEY" and api_key:
                return api_key

    pytest.skip("ANYSEARCH_API_KEY was not found in the environment or .env")


def test_load_api_key_prefers_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANYSEARCH_API_KEY", " environment-key ")

    assert load_api_key() == "environment-key"


def test_live_rest_search_smoke() -> None:
    with Client(api_key=load_api_key()) as client:
        response = client.search("AnySearch", max_results=1)

    assert response.ok
    assert response.data.results


def test_live_mcp_get_sub_domains_smoke() -> None:
    with MCPClient(api_key=load_api_key()) as client:
        text = client.get_sub_domains(domain=Domain.FINANCE)

    assert "finance" in text.lower()


def test_live_rest_get_sub_domains_smoke() -> None:
    with Client(api_key=load_api_key()) as client:
        response = client.get_sub_domains(domains=[Domain.CODE, Domain.FINANCE])

    assert {domain.domain for domain in response.data.domains} == {"code", "finance"}
    assert all(domain.sub_domains for domain in response.data.domains)


def test_live_rest_extract_smoke() -> None:
    with Client(api_key=load_api_key()) as client:
        response = client.extract("https://example.com")

    assert response.data.title
    assert response.data.content
