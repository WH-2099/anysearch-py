from __future__ import annotations

import json

from hypothesis import example, given
from hypothesis import strategies as st

from anysearch_py import MCPToolCall, SearchArguments, SearchRequest, ToolName
from anysearch_py.models import JsonObject

JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text()
)
JSON_VALUES = st.recursive(
    JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=5)
        | st.dictionaries(st.text(), children, max_size=5)
    ),
    max_leaves=20,
)
JSON_OBJECTS = st.dictionaries(st.text(), JSON_VALUES, max_size=5)


@given(params=JSON_OBJECTS)
@example(params={"code": "  indented\n", "nested": {"value": " spaced "}})
def test_rest_extended_parameters_preserve_json_values(params: JsonObject) -> None:
    request = SearchRequest(query="example", params=params)
    assert (
        json.loads(json.dumps(request.to_payload(), allow_nan=False))["params"]
        == params
    )


@given(params=JSON_OBJECTS)
@example(params={"code": "\n    print('hello')\n", "null": None})
def test_mcp_tool_arguments_preserve_json_values(params: JsonObject) -> None:
    call = MCPToolCall.from_arguments(ToolName.SEARCH, params)
    request = call.to_request(1).to_payload()
    assert isinstance(request["params"], dict)
    assert request["params"]["arguments"] == params


@given(params=JSON_OBJECTS)
def test_vertical_arguments_do_not_mutate_callers(params: JsonObject) -> None:
    original = json.dumps(params, allow_nan=False)
    request = SearchArguments.from_input(
        "example", domain="code", sub_domain="code.doc", sub_domain_params=params
    )
    assert request.to_payload()["sub_domain_params"] == params
    assert json.dumps(params, allow_nan=False) == original
