"""HTTP clients for AnySearch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import count
from typing import Any, Self

import urllib3
from urllib3.util import Retry, Timeout

from .exceptions import (
    HTTPStatusError,
    ResponseDecodeError,
    TransportError,
)
from .models import (
    APIErrorDetails,
    BatchSearchArguments,
    Domain,
    ExtractArguments,
    GetSubDomainsArguments,
    JsonObject,
    JsonValue,
    MCPArguments,
    MCPToolCall,
    MCPToolResponse,
    MCPToolResult,
    OutputFormat,
    SearchArgumentInput,
    SearchArguments,
    SearchRequest,
    SearchResponse,
    SearchTag,
    ToolName,
    Zone,
)

API_BASE_URL = "https://api.anysearch.com"
REST_SEARCH_PATH = "/v1/search"
MCP_PATH = "/mcp"
USER_AGENT = "anysearch-py/0.1.0"

DEFAULT_TIMEOUT = Timeout(connect=10.0, read=30.0)
DEFAULT_RETRIES = Retry(
    total=2,
    connect=2,
    read=2,
    status=2,
    backoff_factor=0.25,
    allowed_methods=frozenset({"GET", "POST"}),
    status_forcelist=frozenset({500, 502, 503, 504}),
    raise_on_status=False,
)
HTTP_OK_MIN = 200
HTTP_REDIRECT_MIN = 300


@dataclass(kw_only=True)
class _HTTPClient:
    api_key: str | None = None
    base_url: str = API_BASE_URL
    user_agent: str = USER_AGENT

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _raise_for_http_status(self, response: Any, payload: Any) -> None:
        status = int(getattr(response, "status", 0))
        if HTTP_OK_MIN <= status < HTTP_REDIRECT_MIN:
            return

        details = APIErrorDetails.from_payload(
            payload,
            fallback_message=f"HTTP {status} response from AnySearch",
        )
        headers = getattr(response, "headers", None)
        raise HTTPStatusError(
            details.message,
            status=status,
            code=details.code,
            request_id=details.request_id,
            data=details.data,
            headers={str(key): str(value) for key, value in headers.items()}
            if hasattr(headers, "items")
            else {},
        )


class _SyncHTTPClient(_HTTPClient):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = API_BASE_URL,
        timeout: Timeout = DEFAULT_TIMEOUT,
        retries: Retry | bool | int = DEFAULT_RETRIES,
        user_agent: str = USER_AGENT,
        http: Any | None = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, user_agent=user_agent)
        self.http = http or urllib3.PoolManager(timeout=timeout, retries=retries)
        self.owns_http = http is None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
        self.close()

    def close(self) -> None:
        if self.owns_http and hasattr(self.http, "clear"):
            self.http.clear()

    def post_json(self, path: str, payload: JsonObject) -> Any:
        try:
            response = self.http.request(
                "POST",
                self._url(path),
                headers=self._headers(),
                json=payload,
            )
        except urllib3.exceptions.HTTPError as exc:
            msg = "AnySearch HTTP request failed"
            raise TransportError(msg, cause=exc) from exc

        try:
            decoded = response.json()
        except ValueError as exc:
            raw = getattr(response, "data", None)
            msg = "response body is not valid JSON"
            raise ResponseDecodeError(msg, raw=raw) from exc
        self._raise_for_http_status(response, decoded)
        return decoded


class _AsyncHTTPClient(_HTTPClient):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = API_BASE_URL,
        timeout: Timeout = DEFAULT_TIMEOUT,
        retries: Retry | bool | int = DEFAULT_RETRIES,
        user_agent: str = USER_AGENT,
        http: Any | None = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, user_agent=user_agent)
        self.http = http or urllib3.AsyncPoolManager(timeout=timeout, retries=retries)
        self.owns_http = http is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        del exc_info
        await self.aclose()

    async def aclose(self) -> None:
        if not self.owns_http or not hasattr(self.http, "clear"):
            return
        result = self.http.clear()
        if hasattr(result, "__await__"):
            await result

    async def post_json(self, path: str, payload: JsonObject) -> Any:
        try:
            response = await self.http.request(
                "POST",
                self._url(path),
                headers=self._headers(),
                json=payload,
            )
        except urllib3.exceptions.HTTPError as exc:
            msg = "AnySearch HTTP request failed"
            raise TransportError(msg, cause=exc) from exc

        try:
            decoded = await response.json()
        except ValueError as exc:
            msg = "response body is not valid JSON"
            raise ResponseDecodeError(msg) from exc
        self._raise_for_http_status(response, decoded)
        return decoded


class Client(_SyncHTTPClient):
    """Synchronous AnySearch REST API client."""

    def search(
        self,
        request: SearchRequest | str,
        *,
        max_results: int = 10,
        tag: SearchTag | str | None = None,
        zone: Zone | str | None = None,
        language: str | None = None,
        params: Mapping[str, JsonValue] | None = None,
        output_format: OutputFormat | str = OutputFormat.JSON,
    ) -> SearchResponse:
        search_request = SearchRequest.from_input(
            request,
            max_results=max_results,
            tag=tag,
            zone=zone,
            language=language,
            params=params,
            output_format=output_format,
        )
        payload = self.post_json(REST_SEARCH_PATH, search_request.to_payload())
        return SearchResponse.from_payload(payload)


class MCPClient(_SyncHTTPClient):
    """Synchronous AnySearch MCP tools/call client."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ids = count(1)

    def call_tool(
        self,
        tool: ToolName | str | MCPArguments | MCPToolCall,
        arguments: Mapping[str, JsonValue] | None = None,
    ) -> MCPToolResult:
        tool_call = (
            tool
            if isinstance(tool, MCPToolCall)
            else tool.to_tool_call()
            if isinstance(tool, MCPArguments)
            else MCPToolCall.from_arguments(tool, arguments)
        )
        payload = self.post_json(
            MCP_PATH, tool_call.to_request(next(self.ids)).to_payload()
        )
        return MCPToolResponse.from_payload(payload)

    def search(
        self, arguments: SearchArguments | str | Mapping[str, Any], **kwargs: Any
    ) -> str:
        args = SearchArguments.from_input(arguments, **kwargs)
        return self.call_tool(args).text

    def batch_search(
        self,
        queries: Sequence[SearchArgumentInput] | BatchSearchArguments,
        *,
        domain: Domain | str | None = None,
        sub_domain: str | None = None,
        sub_domain_params: Mapping[str, JsonValue] | str | None = None,
    ) -> str:
        args = (
            queries
            if isinstance(queries, BatchSearchArguments)
            else BatchSearchArguments.from_queries(
                queries,
                domain=domain,
                sub_domain=sub_domain,
                sub_domain_params=sub_domain_params,
            )
        )
        return self.call_tool(args).text

    def get_sub_domains(
        self,
        *,
        domain: Domain | str | None = None,
        domains: Sequence[Domain | str] | None = None,
    ) -> str:
        args = GetSubDomainsArguments.from_selector(domain=domain, domains=domains)
        return self.call_tool(args).text

    def extract(self, url: str) -> str:
        return self.call_tool(ExtractArguments.from_url(url)).text


class AsyncClient(_AsyncHTTPClient):
    """Asynchronous AnySearch REST API client."""

    async def search(
        self,
        request: SearchRequest | str,
        *,
        max_results: int = 10,
        tag: SearchTag | str | None = None,
        zone: Zone | str | None = None,
        language: str | None = None,
        params: Mapping[str, JsonValue] | None = None,
        output_format: OutputFormat | str = OutputFormat.JSON,
    ) -> SearchResponse:
        search_request = SearchRequest.from_input(
            request,
            max_results=max_results,
            tag=tag,
            zone=zone,
            language=language,
            params=params,
            output_format=output_format,
        )
        payload = await self.post_json(REST_SEARCH_PATH, search_request.to_payload())
        return SearchResponse.from_payload(payload)


class AsyncMCPClient(_AsyncHTTPClient):
    """Asynchronous AnySearch MCP tools/call client."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ids = count(1)

    async def call_tool(
        self,
        tool: ToolName | str | MCPArguments | MCPToolCall,
        arguments: Mapping[str, JsonValue] | None = None,
    ) -> MCPToolResult:
        tool_call = (
            tool
            if isinstance(tool, MCPToolCall)
            else tool.to_tool_call()
            if isinstance(tool, MCPArguments)
            else MCPToolCall.from_arguments(tool, arguments)
        )
        payload = await self.post_json(
            MCP_PATH,
            tool_call.to_request(next(self.ids)).to_payload(),
        )
        return MCPToolResponse.from_payload(payload)

    async def search(
        self,
        arguments: SearchArguments | str | Mapping[str, Any],
        **kwargs: Any,
    ) -> str:
        args = SearchArguments.from_input(arguments, **kwargs)
        result = await self.call_tool(args)
        return result.text

    async def batch_search(
        self,
        queries: Sequence[SearchArgumentInput] | BatchSearchArguments,
        *,
        domain: Domain | str | None = None,
        sub_domain: str | None = None,
        sub_domain_params: Mapping[str, JsonValue] | str | None = None,
    ) -> str:
        args = (
            queries
            if isinstance(queries, BatchSearchArguments)
            else BatchSearchArguments.from_queries(
                queries,
                domain=domain,
                sub_domain=sub_domain,
                sub_domain_params=sub_domain_params,
            )
        )
        result = await self.call_tool(args)
        return result.text

    async def get_sub_domains(
        self,
        *,
        domain: Domain | str | None = None,
        domains: Sequence[Domain | str] | None = None,
    ) -> str:
        args = GetSubDomainsArguments.from_selector(domain=domain, domains=domains)
        result = await self.call_tool(args)
        return result.text

    async def extract(self, url: str) -> str:
        result = await self.call_tool(ExtractArguments.from_url(url))
        return result.text
