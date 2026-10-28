from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from anysearch_py import (
    BatchSearchArguments,
    Domain,
    ExtractArguments,
    ExtractResponse,
    GetSubDomainsArguments,
    JSONRPCError,
    MCPToolResponse,
    ResponseValidationError,
    ScoreArguments,
    ScoreFeedback,
    SearchArguments,
    SearchResponse,
    SubDomainsResponse,
    ToolName,
)
from anysearch_py.models import MCPArguments
from tests.support import mcp_payload, sample, tool_schemas


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("rest_search", SearchResponse),
        ("rest_markdown", SearchResponse),
        ("rest_extract", ExtractResponse),
        ("rest_domains", SubDomainsResponse),
    ],
)
def test_recorded_rest_success(
    name: str, model: type[SearchResponse | ExtractResponse | SubDomainsResponse]
) -> None:
    body = sample(name)["body"]
    response = model.from_payload(body)
    assert response.ok
    assert response.request_id == body["request_id"]
    assert response.data.model_dump(mode="json") == body["data"]


@pytest.mark.parametrize(
    "name", ["mcp_search", "mcp_batch", "mcp_extract", "mcp_domains", "mcp_score"]
)
def test_recorded_mcp_success(name: str) -> None:
    body = sample(name)["body"]
    response = MCPToolResponse.from_payload(body, expected_id=body["id"])
    result = body["result"]
    assert response.meta == result.get("_meta")
    assert response.structured_content == result.get("structuredContent")
    assert response.text == "\n\n".join(block["text"] for block in result["content"])


@pytest.mark.parametrize("metadata_id", [None, "", 42, "tool-request-id"])
def test_mcp_tool_error_request_id_precedence(metadata_id: str | int | None) -> None:
    payload = mcp_payload("mcp_missing_query")
    payload["request_id"] = "header-request-id"
    payload["result"]["_meta"] = {"request_id": metadata_id}
    with pytest.raises(JSONRPCError) as caught:
        MCPToolResponse.from_payload(payload, expected_id=1)
    assert caught.value.request_id == (
        "tool-request-id" if metadata_id == "tool-request-id" else "header-request-id"
    )


def test_jsonrpc_error_preserves_details() -> None:
    payload = mcp_payload("mcp_unknown_tool")
    payload["request_id"] = "request-id"
    payload["error"]["data"] = {"field": "name"}
    with pytest.raises(JSONRPCError) as caught:
        MCPToolResponse.from_payload(payload)
    assert caught.value.code == -32602
    assert caught.value.data == {"field": "name"}
    assert caught.value.request_id == "request-id"


def test_future_response_fields_and_non_text_content_are_preserved() -> None:
    rest = sample("rest_search")["body"]
    rest["new_field"] = {"value": 1}
    rest["data"]["results"][0]["provider"] = "new-provider"
    response = SearchResponse.from_payload(rest).model_dump(mode="json")
    assert response["new_field"] == {"value": 1}
    assert response["data"]["results"][0]["provider"] == "new-provider"
    body = mcp_payload("mcp_search")
    body["result"]["content"].extend([
        {"type": "image", "data": "aW1hZ2U=", "mimeType": "image/png"},
        {"type": "text", "text": "second paragraph"},
    ])
    result = MCPToolResponse.from_payload(body)
    assert result.content[1].model_dump()["mimeType"] == "image/png"
    assert result.text.endswith("\n\nsecond paragraph")


@pytest.mark.parametrize("missing", ["title", "url"])
def test_missing_required_result_fields_fail(missing: str) -> None:
    body = sample("rest_search")["body"]
    del body["data"]["results"][0][missing]
    with pytest.raises(ResponseValidationError) as caught:
        SearchResponse.from_payload(body)
    assert caught.value.payload == body


@pytest.mark.parametrize(
    "arguments",
    [
        SearchArguments(query="pytest", max_results=1),
        SearchArguments(
            query="pytest",
            domain=Domain.CODE,
            sub_domain="code.doc",
            sub_domain_params={"library": "pytest"},
            max_results=10,
        ),
        BatchSearchArguments.from_queries(["pytest"] * 5),
        ExtractArguments.from_url("https://example.com"),
        GetSubDomainsArguments(domain=Domain.CODE),
        GetSubDomainsArguments(domains=tuple(Domain)[:5]),
        ScoreArguments(feedbacks=(ScoreFeedback(request_id="x" * 64, score=5),) * 10),
    ],
)
def test_requests_match_published_mcp_schemas(arguments: MCPArguments) -> None:
    schema = tool_schemas()[arguments.tool_name]["inputSchema"]
    Draft202012Validator(schema).validate(arguments.to_payload())


def test_mcp_catalog_and_extract_output_match_published_schemas() -> None:
    schemas = tool_schemas()
    assert set(schemas) == set(ToolName)
    domain_schema = schemas["get_sub_domains"]["inputSchema"]["properties"]["domain"]
    assert set(domain_schema["enum"]) == set(Domain)
    output = sample("mcp_extract")["body"]["result"]["structuredContent"]
    Draft202012Validator(schemas["extract"]["outputSchema"]).validate(output)
