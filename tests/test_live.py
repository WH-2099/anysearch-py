from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator

from anysearch_py import (
    AsyncClient,
    AsyncMCPClient,
    BatchSearchArguments,
    Client,
    Domain,
    ExtractArguments,
    HTTPStatusError,
    JSONRPCError,
    MCPClient,
    ScoreArguments,
    ScoreFeedback,
    SearchArguments,
    ToolName,
)
from tests.support import EXTRACT_URL, opened_client, resolve

pytestmark = pytest.mark.live
QUERY = "pytest official documentation"


@pytest.mark.parametrize("output_format", ["json", "markdown"])
async def test_rest_search(
    live_rest_client: Client | AsyncClient, output_format: str
) -> None:
    response = await resolve(
        live_rest_client.search(QUERY, max_results=1, output_format=output_format)
    )
    assert response.ok
    assert response.request_id
    assert len(response.data.results) == 1
    assert response.data.metadata.total_results == 1
    assert response.data.metadata.search_time_ms >= 0
    assert response.data.results[0].url.host
    if output_format == "markdown":
        assert response.data.results[0].content
        assert response.data.results[0].content.startswith("## ")


async def test_rest_domain_discovery(live_rest_client: Client | AsyncClient) -> None:
    response = await resolve(
        live_rest_client.get_sub_domains(
            domains=[Domain.CODE, Domain.FINANCE, Domain.CODE]
        )
    )
    assert response.ok
    assert response.request_id
    assert {item.domain for item in response.data.domains} == {"code", "finance"}
    code = next(item for item in response.data.domains if item.domain == "code")
    doc = next(item for item in code.sub_domains if item.sub_domain == "code.doc")
    assert doc.params["library"].required


async def test_rest_extract(live_rest_client: Client | AsyncClient) -> None:
    response = await resolve(live_rest_client.extract(EXTRACT_URL))
    assert response.ok
    assert response.request_id
    assert str(response.data.url) == EXTRACT_URL
    assert "# anysearch-py" in response.data.content


@pytest.mark.parametrize(
    ("method", "path", "payload", "error_code"),
    [
        ("POST", "/v1/search", {}, None),
        ("POST", "/v1/extract", {"url": "ftp://example.com"}, "invalid_extract_url"),
        ("GET", "/v1/sub-domains", None, None),
    ],
)
async def test_rest_server_validation(
    live_rest_client: Client | AsyncClient,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    error_code: str | None,
) -> None:
    with pytest.raises(HTTPStatusError) as caught:
        await resolve(live_rest_client.request_json(method, path, payload))
    assert caught.value.status == 400
    assert caught.value.code == -1
    assert caught.value.error_code == error_code
    assert caught.value.request_id


async def test_mcp_discovery_and_schemas(
    live_mcp_client: MCPClient | AsyncMCPClient,
) -> None:
    response = await resolve(
        live_mcp_client.request_json(
            "POST",
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 100,
                "method": "tools/list",
            },
        )
    )
    tools = {tool["name"]: tool for tool in response["result"]["tools"]}
    assert set(ToolName) <= tools.keys()
    domains = tools["get_sub_domains"]["inputSchema"]["properties"]["domain"]["enum"]
    assert set(Domain) == set(domains)
    for arguments in (
        SearchArguments(query=QUERY, max_results=1),
        BatchSearchArguments.from_queries([QUERY]),
        ExtractArguments.from_url(EXTRACT_URL),
        ScoreArguments(feedbacks=(ScoreFeedback(request_id="schema-check", score=1),)),
    ):
        Draft202012Validator(tools[arguments.tool_name]["inputSchema"]).validate(
            arguments.to_payload()
        )
    text = await resolve(
        live_mcp_client.get_sub_domains(domains=[Domain.CODE, Domain.FINANCE])
    )
    assert "code.doc" in text
    assert "finance" in text


async def test_mcp_search(live_mcp_client: MCPClient | AsyncMCPClient) -> None:
    text = await resolve(live_mcp_client.search(QUERY, max_results=1))
    assert "https://docs.pytest.org" in text
    assert "request_id:" in text


async def test_mcp_search_metadata_and_score(
    live_mcp_client: MCPClient | AsyncMCPClient,
) -> None:
    result = await resolve(
        live_mcp_client.call_tool(SearchArguments(query=QUERY, max_results=1))
    )
    assert "https://docs.pytest.org" in result.text
    assert result.meta
    request_id = result.meta["request_id"]
    assert isinstance(request_id, str)
    assert request_id
    assert (
        await resolve(
            live_mcp_client.score([ScoreFeedback(request_id=request_id, score=5)])
        )
        == "success"
    )


async def test_mcp_batch_search(live_mcp_client: MCPClient | AsyncMCPClient) -> None:
    text = await resolve(
        live_mcp_client.batch_search([
            {"query": QUERY, "max_results": 1},
            {
                "query": "Hypothesis official Python testing documentation",
                "max_results": 1,
            },
        ])
    )
    assert "## Query 1:" in text
    assert "## Query 2:" in text
    assert text.count("request_id:") == 2


async def test_mcp_extract(live_mcp_client: MCPClient | AsyncMCPClient) -> None:
    text = await resolve(live_mcp_client.extract(EXTRACT_URL))
    assert "# anysearch-py" in text
    result = await resolve(
        live_mcp_client.call_tool(ExtractArguments.from_url(EXTRACT_URL))
    )
    assert result.structured_content
    assert result.structured_content["url"] == EXTRACT_URL
    assert "# anysearch-py" in result.structured_content["content"]
    assert result.meta
    assert result.meta["request_id"]


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("search", {}, "query"),
        ("extract", {"url": "ftp://example.com"}, "url"),
        ("get_sub_domains", {}, "domain"),
        ("batch_search", {"queries": []}, "queries"),
        ("batch_search", {"queries": [{"query": QUERY}, {}]}, "query"),
        ("score", {"feedbacks": []}, "feedbacks"),
    ],
)
async def test_mcp_server_validation(
    live_mcp_client: MCPClient | AsyncMCPClient,
    tool: str,
    arguments: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(JSONRPCError) as caught:
        await resolve(live_mcp_client.call_tool(tool, arguments))
    assert message in str(caught.value).lower()
    assert caught.value.request_id


@pytest.mark.parametrize("client_type", [Client, AsyncClient])
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("POST", "/v1/search", {"query": QUERY, "max_results": 1}),
        ("POST", "/v1/extract", {"url": EXTRACT_URL}),
        ("GET", "/v1/sub-domains?domain=code", None),
    ],
)
async def test_rest_invalid_key(
    client_type: type[Client | AsyncClient],
    method: str,
    path: str,
    payload: dict[str, Any] | None,
) -> None:
    async with opened_client(
        client_type(api_key="invalid-sdk-contract-test-key")
    ) as client:
        with pytest.raises(HTTPStatusError) as caught:
            await resolve(client.request_json(method, path, payload))
    assert caught.value.status == 401
    assert caught.value.error_code == "invalid_api_key"
    assert caught.value.request_id


@pytest.mark.parametrize("client_type", [MCPClient, AsyncMCPClient])
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search", {"query": QUERY}),
        ("extract", {"url": EXTRACT_URL}),
        ("get_sub_domains", {"domain": "code"}),
    ],
)
async def test_mcp_invalid_key(
    client_type: type[MCPClient | AsyncMCPClient], tool: str, arguments: dict[str, Any]
) -> None:
    async with opened_client(
        client_type(api_key="invalid-sdk-contract-test-key")
    ) as client:
        with pytest.raises(JSONRPCError, match="invalid_api_key") as caught:
            await resolve(client.call_tool(tool, arguments))
    assert caught.value.request_id
