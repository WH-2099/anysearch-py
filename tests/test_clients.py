from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from anysearch_py import (
    APIError,
    AsyncClient,
    AsyncMCPClient,
    Client,
    Domain,
    HTTPStatusError,
    MCPClient,
    ResponseDecodeError,
    SearchRequest,
    SearchResponse,
    SearchTag,
)


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self.data = b"not-json"

    def json(self) -> object:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class FakeHTTP:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def request(self, *args: Any, **kwargs: Any) -> FakeResponse:
        self.calls.append((args, kwargs))
        return self.response


class AsyncFakeResponse(FakeResponse):
    async def json(self) -> object:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class AsyncFakeHTTP:
    def __init__(self, response: AsyncFakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def request(self, *args: Any, **kwargs: Any) -> AsyncFakeResponse:
        self.calls.append((args, kwargs))
        return self.response


def search_payload() -> dict[str, object]:
    return {
        "code": 0,
        "message": "success",
        "request_id": "req-1",
        "data": {
            "results": [
                {
                    "title": "Go 1.26 Release Notes",
                    "url": "https://go.dev/doc/go1.26",
                    "snippet": "Go 1.26 is a major release...",
                },
            ],
            "metadata": {
                "total_results": 1,
                "search_time_ms": 946,
            },
        },
    }


def mcp_payload(text: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": text,
                },
            ],
        },
    }


def call_rest_with_string(client: Client) -> SearchResponse:
    return client.search(
        "Go 1.26 release notes",
        tag=SearchTag.CODE_DOC,
        params={"library": "golang"},
    )


def call_rest_with_model(client: Client) -> SearchResponse:
    return client.search(
        SearchRequest(query="Python docs", max_results=3, language="en-US")
    )


@pytest.mark.parametrize(
    ("caller", "expected_json"),
    [
        pytest.param(
            call_rest_with_string,
            {
                "query": "Go 1.26 release notes",
                "max_results": 10,
                "tag": "code.doc",
                "params": {"library": "golang"},
                "format": "json",
            },
            id="string-request",
        ),
        pytest.param(
            call_rest_with_model,
            {
                "query": "Python docs",
                "max_results": 3,
                "language": "en-US",
                "format": "json",
            },
            id="model-request",
        ),
    ],
)
def test_rest_client_sends_search_payload_matrix(
    caller: Callable[[Client], SearchResponse],
    expected_json: dict[str, object],
) -> None:
    http = FakeHTTP(FakeResponse(search_payload()))
    client = Client(api_key="test-key", http=http)

    response = caller(client)

    assert response.request_id == "req-1"
    assert response.data.metadata.total_results == 1

    args, request_kwargs = http.calls[0]
    assert args[:2] == ("POST", "https://api.anysearch.com/v1/search")
    assert request_kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert request_kwargs["json"] == expected_json


def call_mcp_search(client: MCPClient) -> str:
    return client.search(
        "AAPL",
        domain=Domain.FINANCE,
        sub_domain="finance.quote",
        sub_domain_params="type=stock,symbol=AAPL,cn_code=",
        max_results=5,
    )


def call_mcp_batch_search(client: MCPClient) -> str:
    return client.batch_search(
        [
            "AAPL",
            {"query": "MSFT", "sub_domain_params": "type=stock,symbol=MSFT,cn_code="},
        ],
        domain=Domain.FINANCE,
        sub_domain="finance.quote",
        sub_domain_params="type=stock,symbol=AAPL,cn_code=",
    )


def call_mcp_get_sub_domains(client: MCPClient) -> str:
    return client.get_sub_domains(domains=[Domain.FINANCE, Domain.HEALTH])


def call_mcp_extract(client: MCPClient) -> str:
    return client.extract("https://example.com/article")


@pytest.mark.parametrize(
    ("caller", "tool_name", "expected_arguments"),
    [
        pytest.param(
            call_mcp_search,
            "search",
            {
                "query": "AAPL",
                "domain": "finance",
                "sub_domain": "finance.quote",
                "sub_domain_params": {
                    "type": "stock",
                    "symbol": "AAPL",
                    "cn_code": "",
                },
                "max_results": 5,
            },
            id="search",
        ),
        pytest.param(
            call_mcp_batch_search,
            "batch_search",
            {
                "queries": [
                    {
                        "query": "AAPL",
                        "domain": "finance",
                        "sub_domain": "finance.quote",
                        "sub_domain_params": {
                            "type": "stock",
                            "symbol": "AAPL",
                            "cn_code": "",
                        },
                    },
                    {
                        "query": "MSFT",
                        "domain": "finance",
                        "sub_domain": "finance.quote",
                        "sub_domain_params": {
                            "type": "stock",
                            "symbol": "MSFT",
                            "cn_code": "",
                        },
                    },
                ],
            },
            id="batch-search",
        ),
        pytest.param(
            call_mcp_get_sub_domains,
            "get_sub_domains",
            {"domains": ["finance", "health"]},
            id="get-sub-domains",
        ),
        pytest.param(
            call_mcp_extract,
            "extract",
            {"url": "https://example.com/article"},
            id="extract",
        ),
    ],
)
def test_mcp_client_sends_tool_call_payload_matrix(
    caller: Callable[[MCPClient], str],
    tool_name: str,
    expected_arguments: dict[str, object],
) -> None:
    http = FakeHTTP(FakeResponse(mcp_payload("ok")))
    client = MCPClient(api_key="test-key", http=http)

    assert caller(client) == "ok"

    args, request_kwargs = http.calls[0]
    assert args[:2] == ("POST", "https://api.anysearch.com/mcp")
    assert request_kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert request_kwargs["json"] == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": expected_arguments,
        },
    }


@pytest.mark.parametrize(
    ("response", "expected_type", "expected_code"),
    [
        (
            FakeResponse(
                {
                    "code": -1,
                    "message": "Missing required params",
                    "request_id": "req-err",
                    "data": {"quota_remaining": 0},
                },
            ),
            APIError,
            -1,
        ),
        (
            FakeResponse(
                {"error": "Bad request", "symbol": "BAD_REQUEST"},
                status=400,
                headers={"x-request-id": "http-err"},
            ),
            HTTPStatusError,
            "BAD_REQUEST",
        ),
        (
            FakeResponse(ValueError("bad json")),
            ResponseDecodeError,
            None,
        ),
    ],
)
def test_rest_client_raises_typed_errors(
    response: FakeResponse,
    expected_type: type[Exception],
    expected_code: int | str | None,
) -> None:
    client = Client(http=FakeHTTP(response))

    with pytest.raises(expected_type) as caught:
        client.search("Go")

    assert getattr(caught.value, "code", None) == expected_code


def test_async_clients_use_same_payload_shapes() -> None:
    async def run() -> tuple[str, str, list[tuple[tuple[Any, ...], dict[str, Any]]]]:
        rest_http = AsyncFakeHTTP(AsyncFakeResponse(search_payload()))
        mcp_http = AsyncFakeHTTP(AsyncFakeResponse(mcp_payload("mcp ok")))

        rest_response = await AsyncClient(http=rest_http).search("hello")
        mcp_text = await AsyncMCPClient(http=mcp_http).search("hello")

        return (
            rest_response.data.results[0].snippet,
            mcp_text,
            rest_http.calls + mcp_http.calls,
        )

    snippet, mcp_text, calls = asyncio.run(run())

    assert snippet == "Go 1.26 is a major release..."
    assert mcp_text == "mcp ok"
    assert calls[0][0][:2] == ("POST", "https://api.anysearch.com/v1/search")
    assert calls[1][0][:2] == ("POST", "https://api.anysearch.com/mcp")
