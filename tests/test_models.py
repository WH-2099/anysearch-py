from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import BaseModel, ValidationError

from anysearch_py import (
    APIError,
    BatchSearchArguments,
    Domain,
    ExtractArguments,
    GetSubDomainsArguments,
    JSONRPCError,
    MCPToolCall,
    MCPToolResponse,
    SearchArguments,
    SearchRequest,
    SearchResponse,
    SearchTag,
    SubDomainParams,
    ToolName,
)


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
                    "content": "Detailed content here...",
                },
            ],
            "metadata": {
                "total_results": 1,
                "search_time_ms": 946,
            },
        },
    }


def mcp_payload(text: str, *, is_error: bool = False) -> dict[str, object]:
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
            "isError": is_error,
        },
    }


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        pytest.param(
            SearchRequest(
                query="Go release notes",
                tag=SearchTag.CODE_DOC,
                params={"library": "golang"},
            ),
            {
                "query": "Go release notes",
                "max_results": 10,
                "tag": "code.doc",
                "params": {"library": "golang"},
                "format": "json",
            },
            id="rest-search-request",
        ),
        pytest.param(
            SearchArguments.from_input(
                "AAPL",
                domain=Domain.FINANCE,
                sub_domain="finance.quote",
                sub_domain_params="type=stock,symbol=AAPL,cn_code=",
                max_results=5,
            ),
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
            id="mcp-search-arguments",
        ),
        pytest.param(
            BatchSearchArguments.from_queries(
                [
                    "AAPL",
                    {
                        "query": "MSFT",
                        "sub_domain_params": "type=stock,symbol=MSFT,cn_code=",
                    },
                ],
                domain=Domain.FINANCE,
                sub_domain="finance.quote",
                sub_domain_params="type=stock,symbol=AAPL,cn_code=",
            ),
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
            id="mcp-batch-search-arguments",
        ),
        pytest.param(
            GetSubDomainsArguments.from_selector(domains=[Domain.FINANCE, "health"]),
            {
                "domains": ["finance", "health"],
            },
            id="mcp-get-sub-domains-arguments",
        ),
        pytest.param(
            ExtractArguments.from_url("https://example.com/article"),
            {
                "url": "https://example.com/article",
            },
            id="mcp-extract-arguments",
        ),
    ],
)
def test_request_models_serialize_payload_matrix(
    model: SearchRequest
    | SearchArguments
    | BatchSearchArguments
    | GetSubDomainsArguments
    | ExtractArguments,
    expected: dict[str, object],
) -> None:
    assert model.to_payload() == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "type=stock,symbol=AAPL,cn_code=",
            {"type": "stock", "symbol": "AAPL", "cn_code": ""},
        ),
        ('{"region":"US","extended":true}', {"region": "US", "extended": True}),
    ],
)
def test_sub_domain_params_parse_supported_string_shapes(
    raw: str,
    expected: dict[str, object],
) -> None:
    assert SubDomainParams.model_validate(raw).root == expected


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (SearchRequest, {"query": "x", "tag": "unknown.tag"}),
        (SearchRequest, {"query": "x", "max_results": 21}),
        (SearchArguments, {"query": "x", "domain": "finance"}),
        (SearchArguments, {"query": "x", "sub_domain_params": {"symbol": "AAPL"}}),
        (GetSubDomainsArguments, {}),
        (GetSubDomainsArguments, {"domain": "finance", "domains": ["health"]}),
    ],
)
def test_request_models_validate_core_rules(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def parse_search(payload: dict[str, object]) -> SearchResponse:
    return SearchResponse.from_payload(payload)


def parse_mcp(payload: dict[str, object]) -> object:
    return MCPToolResponse.from_payload(payload)


@pytest.mark.parametrize(
    ("parser", "payload", "expected_type", "expected_code"),
    [
        (
            parse_search,
            {
                "code": -1,
                "message": "Missing required params",
                "request_id": "req-err",
                "data": {"quota_remaining": 0},
            },
            APIError,
            -1,
        ),
        (
            parse_mcp,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32602, "message": "Invalid params"},
            },
            JSONRPCError,
            -32602,
        ),
        (
            parse_mcp,
            mcp_payload("tool failed", is_error=True),
            JSONRPCError,
            None,
        ),
    ],
)
def test_response_models_raise_typed_errors(
    parser: Callable[[dict[str, object]], object],
    payload: dict[str, object],
    expected_type: type[Exception],
    expected_code: int | None,
) -> None:
    with pytest.raises(expected_type) as caught:
        parser(payload)

    assert getattr(caught.value, "code", None) == expected_code


def test_search_response_and_mcp_response_parse_success_payloads() -> None:
    search_response = SearchResponse.from_payload(search_payload())
    mcp_result = MCPToolResponse.from_payload(
        mcp_payload("## finance Domain Capabilities")
    )

    assert search_response.data.results[0].title == "Go 1.26 Release Notes"
    assert mcp_result.text == "## finance Domain Capabilities"


def test_mcp_tool_call_wraps_arguments_as_json_rpc_request() -> None:
    tool_call = MCPToolCall.from_arguments(
        ToolName.SEARCH,
        SearchArguments(query="hello"),
    )

    assert tool_call.to_request(42).to_payload() == {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {
            "name": "search",
            "arguments": {"query": "hello"},
        },
    }
