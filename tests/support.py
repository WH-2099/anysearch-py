from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncGenerator, Awaitable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import SecretStr

from anysearch_py import AsyncClient, AsyncMCPClient, Client, MCPClient

type AnyClient = Client | AsyncClient | MCPClient | AsyncMCPClient

FIXTURES = Path(__file__).parent / "fixtures"
EXTRACT_URL = "https://raw.githubusercontent.com/WH-2099/anysearch-py/v0.3.0/README.md"


def sample(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "responses.json").read_text())["samples"][name]


def mcp_payload(name: str, request_id: int = 1) -> dict[str, Any]:
    payload = sample(name)["body"]
    payload["id"] = request_id
    return payload


def tool_schemas() -> dict[str, Any]:
    data = json.loads((FIXTURES / "mcp_tools.json").read_text())
    return {tool["name"]: tool for tool in data["tools"]}


async def resolve[ValueT](value: ValueT | Awaitable[ValueT]) -> ValueT:
    return await value if isinstance(value, Awaitable) else value


@asynccontextmanager
async def opened_client[ClientT: AnyClient](client: ClientT) -> AsyncGenerator[ClientT]:
    if isinstance(client, AsyncClient | AsyncMCPClient):
        async with client:
            yield client
    else:
        assert isinstance(client, Client | MCPClient)
        with client:
            yield client


def load_api_key(env_file: Path) -> SecretStr | None:
    value = os.getenv("ANYSEARCH_API_KEY", "").strip()
    if not value:
        values = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)
        value = (values.get("ANYSEARCH_API_KEY") or "").strip()
    return SecretStr(value) if value else None


def redact(text: str, api_key: SecretStr | None = None) -> str:
    if api_key is not None:
        text = text.replace(api_key.get_secret_value(), "<redacted>")
    # Anonymous HTTP 402 messages can contain freshly generated credentials.
    return re.sub(
        r"(?im)((?:api_key|password|username)\s*=)[^\r\n\\]+",
        r"\1<redacted>",
        text,
    )
