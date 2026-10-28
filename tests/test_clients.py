from __future__ import annotations

import socket
from importlib.metadata import version
from threading import Event
from typing import Any

import pytest
import urllib3
from pydantic import ValidationError
from pytest_httpserver import HTTPServer
from urllib3.exceptions import NewConnectionError, ReadTimeoutError
from urllib3.util import Timeout
from werkzeug.wrappers import Request, Response

from anysearch_py import (
    APIError,
    AsyncClient,
    AsyncMCPClient,
    BatchSearchArguments,
    Client,
    Domain,
    ExtractRequest,
    HTTPStatusError,
    JSONRPCError,
    MCPClient,
    MCPToolCall,
    ResponseDecodeError,
    ResponseValidationError,
    ScoreArguments,
    ScoreFeedback,
    SearchArguments,
    SearchRequest,
    SearchTag,
    TransportError,
)
from anysearch_py.client import DEFAULT_RETRIES
from tests.support import (
    EXTRACT_URL,
    AnyClient,
    mcp_payload,
    opened_client,
    resolve,
    sample,
)


@pytest.mark.parametrize(
    ("query", "options", "payload"),
    [
        (
            "  pytest 文档  ",
            {
                "max_results": 1,
                "tag": SearchTag.CODE_DOC,
                "zone": "intl",
                "language": "zh-Hans-CN",
                "params": {"library": "pytest", "code": "  indented\n"},
                "output_format": "markdown",
            },
            {
                "query": "pytest 文档",
                "max_results": 1,
                "tag": "code.doc",
                "zone": "intl",
                "language": "zh-Hans-CN",
                "params": {"library": "pytest", "code": "  indented\n"},
                "format": "markdown",
            },
        ),
        (
            SearchRequest(query="pytest", max_results=10),
            {},
            {"query": "pytest", "max_results": 10, "format": "json"},
        ),
    ],
)
async def test_rest_search(
    rest_client: Client | AsyncClient,
    server: HTTPServer,
    query: str | SearchRequest,
    options: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    server.expect_ordered_request(
        "/v1/search", method="POST", json=payload
    ).respond_with_json(sample("rest_search")["body"])
    response = await resolve(rest_client.search(query, **options))
    assert response.ok
    assert response.data.results[0].url.host == "docs.pytest.org"
    assert response.request_id == sample("rest_search")["body"]["request_id"]


@pytest.mark.parametrize("as_model", [False, True])
async def test_rest_extract(
    rest_client: Client | AsyncClient, server: HTTPServer, as_model: bool
) -> None:
    server.expect_ordered_request(
        "/v1/extract", method="POST", json={"url": EXTRACT_URL}
    ).respond_with_json(sample("rest_extract")["body"])
    response = await resolve(
        rest_client.extract(
            ExtractRequest(url=EXTRACT_URL) if as_model else EXTRACT_URL
        )
    )
    assert str(response.data.url) == EXTRACT_URL
    assert response.data.title == ""
    assert response.data.content.startswith("# anysearch-py")


@pytest.mark.parametrize(
    ("selectors", "query_string"),
    [
        ({"domain": Domain.CODE}, "domain=code"),
        (
            {"domains": ["code", "finance", "code"]},
            "domain=code&domain=finance&domain=code",
        ),
    ],
)
async def test_rest_domains(
    rest_client: Client | AsyncClient,
    server: HTTPServer,
    selectors: dict[str, Any],
    query_string: str,
) -> None:
    server.expect_ordered_request(
        "/v1/sub-domains", method="GET", query_string=query_string
    ).respond_with_json(sample("rest_domains")["body"])
    response = await resolve(rest_client.get_sub_domains(**selectors))
    assert response.ok
    assert response.data.domains[0].sub_domains
    assert server.log[0][0].data == b""


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "tool", "arguments", "response_sample"),
    [
        (
            "search",
            ("pytest",),
            {"max_results": 1},
            "search",
            {"query": "pytest", "max_results": 1},
            "mcp_search",
        ),
        (
            "search",
            (SearchArguments(query="pytest"),),
            {},
            "search",
            {"query": "pytest"},
            "mcp_search",
        ),
        (
            "search",
            ({"query": "pytest", "max_results": 1},),
            {},
            "search",
            {"query": "pytest", "max_results": 1},
            "mcp_search",
        ),
        (
            "search",
            ("pytest",),
            {
                "domain": Domain.CODE,
                "sub_domain": "code.doc",
                "sub_domain_params": {"library": "pytest"},
            },
            "search",
            {
                "query": "pytest",
                "domain": "code",
                "sub_domain": "code.doc",
                "sub_domain_params": {"library": "pytest"},
            },
            "mcp_search",
        ),
        (
            "batch_search",
            (["pytest", {"query": "hypothesis"}],),
            {},
            "batch_search",
            {"queries": [{"query": "pytest"}, {"query": "hypothesis"}]},
            "mcp_batch",
        ),
        (
            "batch_search",
            (BatchSearchArguments(queries=(SearchArguments(query="pytest"),)),),
            {},
            "batch_search",
            {"queries": [{"query": "pytest"}]},
            "mcp_batch",
        ),
        (
            "batch_search",
            (["pytest", SearchArguments(query="hypothesis")],),
            {
                "domain": "code",
                "sub_domain": "code.doc",
                "sub_domain_params": {"library": "pytest"},
            },
            "batch_search",
            {
                "queries": [
                    {
                        "query": "pytest",
                        "domain": "code",
                        "sub_domain": "code.doc",
                        "sub_domain_params": {"library": "pytest"},
                    },
                    {
                        "query": "hypothesis",
                        "domain": "code",
                        "sub_domain": "code.doc",
                        "sub_domain_params": {"library": "pytest"},
                    },
                ]
            },
            "mcp_batch",
        ),
        (
            "extract",
            ("https://example.com",),
            {},
            "extract",
            {"url": "https://example.com/"},
            "mcp_extract",
        ),
        (
            "get_sub_domains",
            (),
            {"domain": "code"},
            "get_sub_domains",
            {"domain": "code"},
            "mcp_domains",
        ),
        (
            "get_sub_domains",
            (),
            {"domains": ["code", "finance"]},
            "get_sub_domains",
            {"domains": ["code", "finance"]},
            "mcp_domains",
        ),
        (
            "score",
            ([{"request_id": "search-id", "score": 5}],),
            {},
            "score",
            {"feedbacks": [{"request_id": "search-id", "score": 5}]},
            "mcp_score",
        ),
        (
            "score",
            (
                ScoreArguments(
                    feedbacks=(ScoreFeedback(request_id="search-id", score=5),)
                ),
            ),
            {},
            "score",
            {"feedbacks": [{"request_id": "search-id", "score": 5}]},
            "mcp_score",
        ),
    ],
    ids=[
        "search-string",
        "search-model",
        "search-mapping",
        "search-vertical",
        "batch-mixed",
        "batch-model",
        "batch-shared",
        "extract",
        "domain",
        "domains",
        "score-mapping",
        "score-model",
    ],
)
async def test_mcp_methods(
    mcp_client: MCPClient | AsyncMCPClient,
    server: HTTPServer,
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    tool: str,
    arguments: dict[str, Any],
    response_sample: str,
) -> None:
    body = mcp_payload(response_sample)
    server.expect_ordered_request(
        "/mcp",
        method="POST",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    ).respond_with_json(body)
    text = await resolve(getattr(mcp_client, method)(*args, **kwargs))
    assert text == "\n\n".join(block["text"] for block in body["result"]["content"])


@pytest.mark.parametrize(
    "tool",
    ["extract", MCPToolCall(name="extract", arguments={"url": "https://example.com"})],
)
async def test_call_tool_preserves_metadata_and_increments_ids(
    mcp_client: MCPClient | AsyncMCPClient, server: HTTPServer, tool: str | MCPToolCall
) -> None:
    for request_id in (1, 2):
        server.expect_ordered_request(
            "/mcp",
            method="POST",
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": "extract",
                    "arguments": {"url": "https://example.com"},
                },
            },
        ).respond_with_json(mcp_payload("mcp_extract", request_id))
        result = await resolve(
            mcp_client.call_tool(
                tool, {"url": "https://example.com"} if isinstance(tool, str) else None
            )
        )
        assert (
            result.structured_content
            == sample("mcp_extract")["body"]["result"]["structuredContent"]
        )
        assert result.meta == sample("mcp_extract")["body"]["result"]["_meta"]


async def test_headers_and_base_url(
    transport_client: AnyClient, server: HTTPServer, api_key: str | None
) -> None:
    transport_client.base_url = server.url_for("/prefix///")
    transport_client.user_agent = f"anysearch-test/{version('anysearch-py')}"
    server.expect_ordered_request("/prefix/check", method="GET").respond_with_json({
        "ok": True
    })
    assert await resolve(transport_client.request_json("GET", "///check")) == {
        "ok": True
    }
    headers = server.log[0][0].headers
    assert headers.get("Authorization") == (f"Bearer {api_key}" if api_key else None)
    assert headers["User-Agent"] == transport_client.user_agent
    assert headers["Accept"] == "application/json"
    assert headers["Content-Type"] == "application/json"
    expected_mcp = (
        "mcp/1.0.0"
        if isinstance(transport_client, MCPClient | AsyncMCPClient)
        else None
    )
    assert headers.get("X-Anysearch-Client") == expected_mcp
    assert api_key is None or api_key not in repr(transport_client)


@pytest.mark.parametrize(
    "name",
    [
        "rest_missing_query",
        "rest_invalid_url",
        "rest_missing_domains",
        "rest_invalid_auth",
    ],
)
async def test_recorded_http_errors(
    transport_client: AnyClient, server: HTTPServer, name: str
) -> None:
    recorded = sample(name)
    server.expect_ordered_request("/error").respond_with_json(
        recorded["body"], status=recorded["status"], headers=recorded["headers"]
    )
    with pytest.raises(HTTPStatusError) as caught:
        await resolve(transport_client.request_json("POST", "/error"))
    error = caught.value
    assert error.status == recorded["status"]
    assert error.code == recorded["body"]["code"]
    assert error.error_code == recorded["body"].get("error_code")
    assert error.request_id == recorded["body"]["request_id"]
    assert str(error) == recorded["body"]["message"]


@pytest.mark.parametrize("status", [302, 429, 500, 503])
async def test_http_failures_are_not_replayed(
    transport_client: AnyClient, server: HTTPServer, status: int
) -> None:
    server.expect_request("/failure", method="POST").respond_with_data(
        "<html>unavailable</html>",
        status=status,
        headers={
            "Retry-After": "0",
            "X-Request-ID": "http-error",
            "Location": server.url_for("/unexpected"),
        },
    )
    with pytest.raises(HTTPStatusError) as caught:
        await resolve(transport_client.request_json("POST", "/failure"))
    assert caught.value.status == status
    assert caught.value.request_id == "http-error"
    assert caught.value.headers["Retry-After"] == "0"
    assert caught.value.data == "<html>unavailable</html>"
    assert len(server.log) == 1


@pytest.mark.parametrize("raw", [b"not-json", b"", b"\xff"])
async def test_invalid_json_preserves_bytes(
    transport_client: AnyClient, server: HTTPServer, raw: bytes
) -> None:
    server.expect_ordered_request("/invalid").respond_with_data(raw)
    with pytest.raises(ResponseDecodeError) as caught:
        await resolve(transport_client.request_json("GET", "/invalid"))
    assert caught.value.raw == raw
    assert isinstance(caught.value.__cause__, ValueError)


@pytest.mark.parametrize("body_id", [None, "", "body-id"])
async def test_rest_business_error_uses_request_id(
    rest_client: Client | AsyncClient, server: HTTPServer, body_id: str | None
) -> None:
    payload = {"code": -1, "message": "No quota", "data": {"quota_remaining": 0}}
    if body_id is not None:
        payload["request_id"] = body_id
    server.expect_ordered_request("/v1/search").respond_with_json(
        payload, headers={"x-request-id": "header-id"}
    )
    with pytest.raises(APIError) as caught:
        await resolve(rest_client.search("pytest"))
    assert type(caught.value) is APIError
    assert caught.value.request_id == (body_id or "header-id")
    assert caught.value.data == {"quota_remaining": 0}


@pytest.mark.parametrize(
    "name",
    [
        "mcp_unknown_tool",
        "mcp_missing_query",
        "mcp_invalid_url",
        "mcp_empty_batch",
        "mcp_invalid_batch",
        "mcp_missing_domains",
        "mcp_empty_score",
        "mcp_invalid_auth",
    ],
)
async def test_recorded_mcp_errors_keep_request_id(
    mcp_client: MCPClient | AsyncMCPClient, server: HTTPServer, name: str
) -> None:
    payload = mcp_payload(name)
    server.expect_ordered_request("/mcp").respond_with_json(
        payload, headers={"X-Request-ID": "header-id"}
    )
    with pytest.raises(JSONRPCError) as caught:
        await resolve(mcp_client.call_tool("search", {}))
    expected_id = (
        payload.get("result", {}).get("_meta", {}).get("request_id", "header-id")
    )
    assert caught.value.request_id == expected_id
    assert caught.value.code == payload.get("error", {}).get("code")


async def test_mcp_rejects_mismatched_response_id(
    mcp_client: MCPClient | AsyncMCPClient, server: HTTPServer
) -> None:
    server.expect_ordered_request("/mcp").respond_with_json(
        mcp_payload("mcp_search", 2)
    )
    with pytest.raises(ResponseValidationError, match="id"):
        await resolve(mcp_client.search("pytest"))


@pytest.mark.parametrize("query", [" ", SearchRequest(query="pytest")])
async def test_invalid_rest_arguments_fail_before_network(
    rest_client: Client | AsyncClient, server: HTTPServer, query: str | SearchRequest
) -> None:
    with pytest.raises(ValueError, match=r"max_results|SearchRequest"):
        await resolve(rest_client.search(query, max_results=0))
    assert not server.log


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "error"),
    [
        ("search", (SearchArguments(query="pytest"),), {"max_results": 1}, ValueError),
        ("batch_search", ("abc",), {}, TypeError),
        (
            "batch_search",
            (BatchSearchArguments(queries=(SearchArguments(query="pytest"),)),),
            {"domain": Domain.GENERAL},
            ValueError,
        ),
        ("score", ([],), {}, ValidationError),
        ("get_sub_domains", (), {}, ValidationError),
        ("extract", ("ftp://example.com",), {}, ValidationError),
    ],
)
async def test_invalid_mcp_arguments_fail_before_network(
    mcp_client: MCPClient | AsyncMCPClient,
    server: HTTPServer,
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        await resolve(getattr(mcp_client, method)(*args, **kwargs))
    assert not server.log


async def test_connection_errors_preserve_cause(transport_client: AnyClient) -> None:
    with socket.socket() as unused_port:
        unused_port.bind(("127.0.0.1", 0))
        transport_client.base_url = f"http://127.0.0.1:{unused_port.getsockname()[1]}"
        with pytest.raises(TransportError) as caught:
            await resolve(transport_client.request_json("POST", "/unreachable"))
    assert isinstance(caught.value.__cause__, urllib3.exceptions.HTTPError)


async def test_read_timeouts_are_not_replayed(transport_client: AnyClient) -> None:
    release = Event()
    attempts: list[str] = []

    def blocked(request: Request) -> Response:
        attempts.append(request.path)
        release.wait(timeout=2)
        return Response("{}", content_type="application/json")

    with HTTPServer(threaded=True) as server:
        server.expect_request("/slow").respond_with_handler(blocked)
        transport_client.base_url = server.url_for("/")
        transport_client.http.connection_pool_kw["timeout"] = Timeout(
            connect=1, read=0.02
        )
        try:
            with pytest.raises(TransportError) as caught:
                await resolve(transport_client.request_json("POST", "/slow"))
            assert isinstance(caught.value.__cause__, ReadTimeoutError)
            assert attempts == ["/slow"]
        finally:
            release.set()
        server.check()


@pytest.mark.parametrize(
    "client_type", [Client, AsyncClient, MCPClient, AsyncMCPClient]
)
@pytest.mark.parametrize("external", [False, True])
async def test_context_manager_closes_only_owned_pools(
    client_type: type[AnyClient], server: HTTPServer, external: bool
) -> None:
    asynchronous = client_type in {AsyncClient, AsyncMCPClient}
    pool = (
        (urllib3.AsyncPoolManager() if asynchronous else urllib3.PoolManager())
        if external
        else None
    )
    client = client_type(base_url=server.url_for("/"), http=pool)
    server.expect_request("/pool").respond_with_json({})
    try:
        async with opened_client(client):
            await resolve(client.request_json("GET", "/pool"))
            assert len(client.http.pools) == 1
        assert len(client.http.pools) == (1 if external else 0)
    finally:
        if pool is not None:
            await resolve(pool.clear())


def test_default_retries_only_retry_connection_failures() -> None:
    assert DEFAULT_RETRIES.read == 0
    assert DEFAULT_RETRIES.redirect == 0
    assert DEFAULT_RETRIES.status == 0
    assert DEFAULT_RETRIES.other == 0
    with urllib3.HTTPConnectionPool("localhost") as pool:
        retry = DEFAULT_RETRIES.increment(
            method="POST",
            url="/search",
            error=NewConnectionError(pool, "connection failed"),
        )
        assert retry.connect == 1
        with pytest.raises(ReadTimeoutError):
            DEFAULT_RETRIES.increment(
                method="POST",
                url="/search",
                error=ReadTimeoutError(pool, "/search", "read timed out"),
            )
