from __future__ import annotations

import asyncio
from collections.abc import Callable
from importlib.metadata import version
from typing import Any

import pytest
import urllib3
from urllib3.exceptions import NewConnectionError, ReadTimeoutError

from anysearch_py import (
    APIError,
    AsyncClient,
    AsyncMCPClient,
    BatchSearchArguments,
    Client,
    Domain,
    ExtractRequest,
    HTTPStatusError,
    MCPClient,
    ResponseDecodeError,
    ResponseValidationError,
    ScoreArguments,
    ScoreFeedback,
    SearchArguments,
    SearchRequest,
    SearchResponse,
    SearchTag,
    TransportError,
)
from anysearch_py.client import DEFAULT_RETRIES


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        data: bytes = b"not-json",
    ) -> None:
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self.data = data

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

    def __bool__(self) -> bool:
        return False


class AsyncFakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        data: bytes = b"not-json",
    ) -> None:
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self._data = data

    @property
    async def data(self) -> bytes:
        return self._data

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

    def __bool__(self) -> bool:
        return False


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


def mcp_payload(text: str, *, request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
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
    assert request_kwargs["headers"]["User-Agent"] == (
        f"anysearch-py/{version('anysearch-py')}"
    )
    assert "X-Anysearch-Client" not in request_kwargs["headers"]
    assert request_kwargs["json"] == expected_json


def call_mcp_search(client: MCPClient) -> str:
    return client.search(
        "AAPL",
        domain=Domain.FINANCE,
        sub_domain="finance.quote",
        sub_domain_params={"type": "stock", "symbol": "AAPL", "cn_code": ""},
        max_results=5,
    )


def call_mcp_batch_search(client: MCPClient) -> str:
    return client.batch_search(
        [
            "AAPL",
            {
                "query": "MSFT",
                "sub_domain_params": {
                    "type": "stock",
                    "symbol": "MSFT",
                    "cn_code": "",
                },
            },
        ],
        domain=Domain.FINANCE,
        sub_domain="finance.quote",
        sub_domain_params={"type": "stock", "symbol": "AAPL", "cn_code": ""},
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
    assert request_kwargs["headers"]["X-Anysearch-Client"] == "mcp/1.0.0"
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
    ("response", "expected_type", "expected_code", "expected_request_id"),
    [
        (
            FakeResponse(
                {
                    "code": -1,
                    "message": "Missing required params",
                    "data": {"quota_remaining": 0},
                },
                headers={"X-Request-ID": "req-err"},
            ),
            APIError,
            -1,
            "req-err",
        ),
        (
            FakeResponse(
                {"error": "Bad request", "symbol": "BAD_REQUEST"},
                status=400,
                headers={"x-request-id": "http-err"},
            ),
            HTTPStatusError,
            "BAD_REQUEST",
            "http-err",
        ),
        (
            FakeResponse(ValueError("bad json")),
            ResponseDecodeError,
            None,
            None,
        ),
    ],
)
def test_rest_client_raises_typed_errors(
    response: FakeResponse,
    expected_type: type[Exception],
    expected_code: int | str | None,
    expected_request_id: str | None,
) -> None:
    client = Client(http=FakeHTTP(response))

    with pytest.raises(expected_type) as caught:
        client.search("Go")

    assert getattr(caught.value, "code", None) == expected_code
    assert getattr(caught.value, "request_id", None) == expected_request_id


def test_non_json_http_errors_preserve_http_metadata() -> None:
    response = FakeResponse(
        ValueError("bad json"),
        status=503,
        headers={"Retry-After": "30", "X-Request-ID": "req-http"},
        data=b"<html>unavailable</html>",
    )

    with pytest.raises(HTTPStatusError) as caught:
        Client(http=FakeHTTP(response)).search("Go")

    assert caught.value.status == 503
    assert caught.value.request_id == "req-http"
    assert caught.value.headers["Retry-After"] == "30"
    assert caught.value.data == "<html>unavailable</html>"


def test_successful_non_json_response_preserves_raw_body() -> None:
    with pytest.raises(ResponseDecodeError) as caught:
        Client(http=FakeHTTP(FakeResponse(ValueError("bad json")))).search("Go")

    assert caught.value.raw == b"not-json"


def test_default_retries_only_retry_connection_failures() -> None:
    assert DEFAULT_RETRIES.read == 0
    assert DEFAULT_RETRIES.redirect == 0
    assert DEFAULT_RETRIES.status == 0
    assert DEFAULT_RETRIES.other == 0
    assert not DEFAULT_RETRIES.is_retry("POST", 500)
    assert not DEFAULT_RETRIES.is_retry("POST", 503, has_retry_after=True)
    assert not DEFAULT_RETRIES.is_retry("POST", 429, has_retry_after=True)

    pool = urllib3.HTTPConnectionPool("api.anysearch.com")
    after_connect = DEFAULT_RETRIES.increment(
        method="POST",
        url="https://api.anysearch.com/v1/search",
        error=NewConnectionError(pool, "connection failed"),
    )
    assert after_connect.connect == 1

    with pytest.raises(ReadTimeoutError):
        DEFAULT_RETRIES.increment(
            method="POST",
            url="https://api.anysearch.com/v1/search",
            error=ReadTimeoutError(pool, "/v1/search", "read timed out"),
        )


def test_client_repr_does_not_expose_api_key() -> None:
    assert "super-secret" not in repr(
        Client(api_key="super-secret", http=FakeHTTP(FakeResponse(search_payload())))
    )


def test_prebuilt_requests_reject_ignored_modifiers() -> None:
    http = FakeHTTP(FakeResponse(search_payload()))
    request = SearchRequest(query="Go", max_results=2)
    batch = BatchSearchArguments(queries=(SearchArguments(query="Go"),))
    client = Client(http=http)
    mcp_client = MCPClient(http=http)

    with pytest.raises(ValueError, match="SearchRequest"):
        client.search(request, max_results=10)
    with pytest.raises(ValueError, match="BatchSearchArguments"):
        mcp_client.batch_search(batch, domain=Domain.GENERAL)
    with pytest.raises(TypeError, match="sequence"):
        mcp_client.batch_search("abc")

    async def run() -> None:
        async_http = AsyncFakeHTTP(AsyncFakeResponse(search_payload()))
        async_client = AsyncClient(http=async_http)
        async_mcp_client = AsyncMCPClient(http=async_http)

        with pytest.raises(ValueError, match="SearchRequest"):
            await async_client.search(request, max_results=10)
        with pytest.raises(ValueError, match="BatchSearchArguments"):
            await async_mcp_client.batch_search(batch, domain=Domain.GENERAL)
        with pytest.raises(TypeError, match="sequence"):
            await async_mcp_client.batch_search("abc")

        assert not async_http.calls

    asyncio.run(run())

    assert not http.calls


def test_async_clients_use_same_payload_shapes() -> None:
    async def run() -> tuple[
        str | None, str, list[tuple[tuple[Any, ...], dict[str, Any]]]
    ]:
        rest_http = AsyncFakeHTTP(AsyncFakeResponse(search_payload()))
        mcp_http = AsyncFakeHTTP(AsyncFakeResponse(mcp_payload("mcp ok")))

        rest_response = await AsyncClient(http=rest_http).search(
            SearchRequest(query="hello")
        )
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
    assert calls[1][1]["headers"]["X-Anysearch-Client"] == "mcp/1.0.0"


def test_mcp_clients_reject_mismatched_response_ids() -> None:
    with pytest.raises(ResponseValidationError, match="id"):
        MCPClient(
            http=FakeHTTP(FakeResponse(mcp_payload("wrong", request_id=2)))
        ).search("hello")

    async def run() -> None:
        client = AsyncMCPClient(
            http=AsyncFakeHTTP(AsyncFakeResponse(mcp_payload("wrong", request_id=2)))
        )
        with pytest.raises(ResponseValidationError, match="id"):
            await client.search("hello")

    asyncio.run(run())


def test_async_non_json_responses_preserve_error_semantics() -> None:
    async def run() -> tuple[HTTPStatusError, ResponseDecodeError, APIError]:
        error_response = AsyncFakeResponse(
            ValueError("bad json"),
            status=503,
            headers={"Retry-After": "30", "x-request-id": "req-async"},
            data=b"<html>unavailable</html>",
        )
        decode_response = AsyncFakeResponse(
            ValueError("bad json"),
            data=b"not-json-async",
        )
        api_response = AsyncFakeResponse(
            {"code": -1, "message": "bad request", "data": None},
            headers={"x-request-id": "req-api"},
        )

        with pytest.raises(HTTPStatusError) as http_error:
            await AsyncClient(http=AsyncFakeHTTP(error_response)).search("Go")
        with pytest.raises(ResponseDecodeError) as decode_error:
            await AsyncClient(http=AsyncFakeHTTP(decode_response)).search("Go")
        with pytest.raises(APIError) as api_error:
            await AsyncClient(http=AsyncFakeHTTP(api_response)).search("Go")
        return http_error.value, decode_error.value, api_error.value

    http_error, decode_error, api_error = asyncio.run(run())

    assert http_error.status == 503
    assert http_error.request_id == "req-async"
    assert http_error.data == "<html>unavailable</html>"
    assert decode_error.raw == b"not-json-async"
    assert api_error.request_id == "req-api"


def test_transport_errors_are_wrapped() -> None:
    class FailingHTTP:
        def request(self, *_: Any, **__: Any) -> None:
            raise urllib3.exceptions.HTTPError

    class AsyncFailingHTTP:
        async def request(self, *_: Any, **__: Any) -> None:
            raise urllib3.exceptions.HTTPError

    with pytest.raises(TransportError) as sync_error:
        Client(http=FailingHTTP()).search("hello")

    async def run() -> TransportError:
        with pytest.raises(TransportError) as async_error:
            await AsyncClient(http=AsyncFailingHTTP()).search("hello")
        return async_error.value

    async_error = asyncio.run(run())

    assert isinstance(sync_error.value.__cause__, urllib3.exceptions.HTTPError)
    assert isinstance(async_error.__cause__, urllib3.exceptions.HTTPError)


def test_async_client_awaits_owned_pool_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OwnedAsyncHTTP:
        cleared = False

        async def clear(self) -> None:
            self.cleared = True

    http = OwnedAsyncHTTP()
    monkeypatch.setattr(urllib3, "AsyncPoolManager", lambda **_: http)

    async def run() -> None:
        client = AsyncClient()
        await client.aclose()

    asyncio.run(run())

    assert http.cleared


@pytest.mark.parametrize(
    "url",
    ["https://example.com/article", ExtractRequest(url="https://example.com/article")],
)
def test_rest_extract_clients_send_and_parse_documented_payload(
    url: ExtractRequest | str,
) -> None:
    payload = {
        "code": 0,
        "message": "success",
        "data": {
            "url": "https://example.com/article",
            "title": "Example Article",
            "content": "# Extracted content",
        },
    }
    http = FakeHTTP(FakeResponse(payload, headers={"X-Request-ID": "req-extract"}))
    async_http = AsyncFakeHTTP(
        AsyncFakeResponse(payload, headers={"X-Request-ID": "req-extract"})
    )

    response = Client(http=http).extract(url)
    async_response = asyncio.run(AsyncClient(http=async_http).extract(url))

    assert response == async_response
    assert response.data.title == "Example Article"
    assert response.data.content == "# Extracted content"
    assert response.request_id == "req-extract"
    assert http.calls == async_http.calls
    args, kwargs = http.calls[0]
    assert args == ("POST", "https://api.anysearch.com/v1/extract")
    assert kwargs["json"] == {"url": "https://example.com/article"}


@pytest.mark.parametrize(
    ("selectors", "fields"),
    [
        ({"domain": Domain.CODE}, [("domain", "code")]),
        (
            {"domains": [Domain.CODE, "finance", "code"]},
            [("domain", "code"), ("domain", "finance"), ("domain", "code")],
        ),
        ({"domain": "unknown"}, [("domain", "unknown")]),
    ],
)
def test_rest_domain_clients_use_repeated_get_parameters(
    selectors: dict[str, Any], fields: list[tuple[str, str]]
) -> None:
    domains = (
        []
        if selectors.get("domain") == "unknown"
        else [
            {
                "domain": "code",
                "description": "Developer documentation and code search",
                "sub_domains": [
                    {
                        "sub_domain": "code.doc",
                        "description": "Documentation",
                        "params": {
                            "library": {
                                "description": "Library name",
                                "required": True,
                                "sort_order": 0,
                            }
                        },
                    },
                    {"sub_domain": "code.snippet", "description": "Code search"},
                ],
            }
        ]
    )
    payload = {"code": 0, "message": "success", "data": {"domains": domains}}
    http = FakeHTTP(FakeResponse(payload))
    async_http = AsyncFakeHTTP(AsyncFakeResponse(payload))

    response = Client(http=http).get_sub_domains(**selectors)
    async_response = asyncio.run(
        AsyncClient(http=async_http).get_sub_domains(**selectors)
    )

    assert response == async_response
    assert http.calls == async_http.calls
    args, kwargs = http.calls[0]
    assert args == ("GET", "https://api.anysearch.com/v1/sub-domains")
    assert kwargs["fields"] == fields
    assert kwargs["json"] is None
    if domains:
        capabilities = response.data.domains[0]
        assert capabilities.sub_domains[0].params["library"].required
        assert capabilities.sub_domains[1].params == {}
    else:
        assert not response.data.domains


@pytest.mark.parametrize(
    ("method", "arguments"),
    [
        ("search", {"query": "hello"}),
        ("extract", {"url": "https://example.com/article"}),
        ("get_sub_domains", {"domain": "code"}),
    ],
)
@pytest.mark.parametrize("status", [200, 400])
def test_rest_clients_preserve_stable_error_codes(
    method: str, arguments: dict[str, str], status: int
) -> None:
    payload = {
        "code": -1,
        "message": "Invalid request",
        "error_code": "invalid_extract_url",
    }
    headers = {"X-Request-ID": "req-error"}
    http = FakeHTTP(FakeResponse(payload, status=status, headers=headers))
    async_http = AsyncFakeHTTP(
        AsyncFakeResponse(payload, status=status, headers=headers)
    )
    error_type = APIError if status == 200 else HTTPStatusError

    with pytest.raises(error_type) as sync_error:
        getattr(Client(http=http), method)(**arguments)
    with pytest.raises(error_type) as async_error:
        asyncio.run(getattr(AsyncClient(http=async_http), method)(**arguments))

    for error in (sync_error.value, async_error.value):
        assert error.code == -1
        assert error.error_code == "invalid_extract_url"
        assert error.request_id == "req-error"


@pytest.mark.parametrize(
    "feedbacks",
    [
        [{"request_id": "req-search", "score": 5}],
        ScoreArguments(feedbacks=(ScoreFeedback(request_id="req-search", score=5),)),
    ],
)
def test_mcp_score_clients_send_validated_feedback(
    feedbacks: Any,
) -> None:
    http = FakeHTTP(FakeResponse(mcp_payload("success")))
    async_http = AsyncFakeHTTP(AsyncFakeResponse(mcp_payload("success")))

    assert MCPClient(http=http).score(feedbacks) == "success"
    assert asyncio.run(AsyncMCPClient(http=async_http).score(feedbacks)) == "success"
    assert http.calls == async_http.calls
    assert http.calls[0][1]["json"]["params"] == {
        "name": "score",
        "arguments": {"feedbacks": [{"request_id": "req-search", "score": 5}]},
    }


def test_mcp_score_rejects_invalid_feedback_before_sending() -> None:
    http = FakeHTTP(FakeResponse(mcp_payload("success")))
    async_http = AsyncFakeHTTP(AsyncFakeResponse(mcp_payload("success")))

    with pytest.raises(ValueError, match="feedbacks"):
        MCPClient(http=http).score([])
    with pytest.raises(ValueError, match="feedbacks"):
        asyncio.run(AsyncMCPClient(http=async_http).score([]))
    assert not http.calls
    assert not async_http.calls
