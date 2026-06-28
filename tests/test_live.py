from __future__ import annotations

from pathlib import Path

import pytest

from anysearch_py import Client, Domain, MCPClient

ENV_FILES = (Path(".env"), Path("anysearch-skill/.env"))


def load_api_key() -> str:
    for env_file in ENV_FILES:
        if not env_file.is_file():
            continue

        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, _, value = stripped.partition("=")
            if key.strip().lstrip("\ufeff") == "ANYSEARCH_API_KEY":
                return value.strip().strip("\"'")

    pytest.skip("ANYSEARCH_API_KEY was not found in .env or anysearch-skill/.env")


def test_live_rest_search_smoke() -> None:
    with Client(api_key=load_api_key()) as client:
        response = client.search("AnySearch", max_results=1)

    assert response.ok
    assert response.data.results


def test_live_mcp_get_sub_domains_smoke() -> None:
    with MCPClient(api_key=load_api_key()) as client:
        text = client.get_sub_domains(domain=Domain.FINANCE)

    assert "finance" in text.lower()
