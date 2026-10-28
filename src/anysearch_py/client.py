"""HTTP clients for AnySearch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import version
from itertools import count
from typing import Any, ClassVar, Self

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
    ExtractRequest,
    ExtractResponse,
    GetSubDomainsArguments,
    GetSubDomainsRequest,
    JsonObject,
    JsonValue,
    MCPArguments,
    MCPToolCall,
    MCPToolResponse,
    MCPToolResult,
    OutputFormat,
    ScoreArguments,
    ScoreFeedback,
    SearchArgumentInput,
    SearchArguments,
    SearchRequest,
    SearchResponse,
    SearchTag,
    SubDomainsResponse,
    ToolName,
    Zone,
)

API_BASE_URL = "https://api.anysearch.com"
REST_SEARCH_PATH = "/v1/search"
REST_EXTRACT_PATH = "/v1/extract"
REST_SUB_DOMAINS_PATH = "/v1/sub-domains"
MCP_PATH = "/mcp"
MCP_CLIENT = "mcp/1.0.0"
USER_AGENT = f"anysearch-py/{version('anysearch-py')}"

DEFAULT_TIMEOUT = Timeout(connect=10.0, read=30.0)
DEFAULT_RETRIES = Retry(
    total=2,
    connect=2,
    read=0,
    redirect=False,
    status=0,
    other=0,
    backoff_factor=0.25,
)
HTTP_OK_MIN = 200
HTTP_REDIRECT_MIN = 300


@dataclass(kw_only=True)
class _HTTPClient:
    api_key: str | None = field(default=None, repr=False)
    base_url: str = API_BASE_URL
    user_agent: str = USER_AGENT
    _mcp_client: ClassVar[str | None] = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        if self._mcp_client:
            headers["X-Anysearch-Client"] = self._mcp_client
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _response_headers(response: Any) -> dict[str, str]:
        headers = getattr(response, "headers", None)
        return (
            {str(key): str(value) for key, value in headers.items()}
            if hasattr(headers, "items")
            else {}
        )

    @staticmethod
    def _request_id_from_headers(headers: Mapping[str, str]) -> str | None:
        return next(
            (value for key, value in headers.items() if key.lower() == "x-request-id"),
            None,
        )

    def _backfill_request_id(self, response: Any, payload: Any) -> Any:
        if (
            not isinstance(payload, dict)
            or "code" not in payload
            or payload.get("request_id")
        ):
            return payload
        request_id = self._request_id_from_headers(self._response_headers(response))
        return {**payload, "request_id": request_id} if request_id else payload

    def _raise_for_http_status(self, response: Any, payload: Any) -> None:
        status = int(getattr(response, "status", 0))
        if HTTP_OK_MIN <= status < HTTP_REDIRECT_MIN:
            return

        details = APIErrorDetails.from_payload(
            payload,
            fallback_message=f"HTTP {status} response from AnySearch",
        )
        response_headers = self._response_headers(response)
        request_id = details.request_id or self._request_id_from_headers(
            response_headers
        )
        raise HTTPStatusError(
            details.message,
            status=status,
            code=details.code,
            error_code=details.error_code,
            request_id=request_id,
            data=details.data,
            headers=response_headers,
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
        self.http = (
            http
            if http is not None
            else urllib3.PoolManager(timeout=timeout, retries=retries)
        )
        self.owns_http = http is None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
        self.close()

    def close(self) -> None:
        if self.owns_http:
            self.http.clear()

    def request_json(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        fields: Sequence[tuple[str, str]] | None = None,
    ) -> Any:
        try:
            response = self.http.request(
                method,
                self._url(path),
                headers=self._headers(),
                json=payload,
                fields=fields,
            )
        except urllib3.exceptions.HTTPError as exc:
            msg = "AnySearch HTTP request failed"
            raise TransportError(msg, cause=exc) from exc

        try:
            decoded = response.json()
        except ValueError as exc:
            raw = getattr(response, "data", None)
            self._raise_for_http_status(response, raw)
            msg = "response body is not valid JSON"
            raise ResponseDecodeError(msg, raw=raw) from exc
        self._raise_for_http_status(response, decoded)
        return self._backfill_request_id(response, decoded)


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
        self.http = (
            http
            if http is not None
            else urllib3.AsyncPoolManager(timeout=timeout, retries=retries)
        )
        self.owns_http = http is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        del exc_info
        await self.aclose()

    async def aclose(self) -> None:
        if self.owns_http:
            await self.http.clear()

    async def request_json(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
        *,
        fields: Sequence[tuple[str, str]] | None = None,
    ) -> Any:
        try:
            response = await self.http.request(
                method,
                self._url(path),
                headers=self._headers(),
                json=payload,
                fields=fields,
            )
        except urllib3.exceptions.HTTPError as exc:
            msg = "AnySearch HTTP request failed"
            raise TransportError(msg, cause=exc) from exc

        try:
            decoded = await response.json()
        except ValueError as exc:
            raw = await response.data
            self._raise_for_http_status(response, raw)
            msg = "response body is not valid JSON"
            raise ResponseDecodeError(msg, raw=raw) from exc
        self._raise_for_http_status(response, decoded)
        return self._backfill_request_id(response, decoded)


class Client(_SyncHTTPClient):
    """Synchronous AnySearch REST API client."""

    def search(
        self,
        query: SearchRequest | str,
        *,
        max_results: int | None = None,
        tag: SearchTag | str | None = None,
        zone: Zone | str | None = None,
        language: str | None = None,
        params: Mapping[str, JsonValue] | None = None,
        output_format: OutputFormat | str | None = None,
    ) -> SearchResponse:
        search_request = SearchRequest.from_input(
            query,
            max_results=max_results,
            tag=tag,
            zone=zone,
            language=language,
            params=params,
            output_format=output_format,
        )
        payload = self.request_json(
            "POST", REST_SEARCH_PATH, search_request.to_payload()
        )
        return SearchResponse.from_payload(payload)

    def extract(self, url: ExtractRequest | str) -> ExtractResponse:
        request = (
            url if isinstance(url, ExtractRequest) else ExtractRequest.from_url(url)
        )
        payload = self.request_json("POST", REST_EXTRACT_PATH, request.to_payload())
        return ExtractResponse.from_payload(payload)

    def get_sub_domains(
        self,
        *,
        domain: Domain | str | None = None,
        domains: Sequence[Domain | str] | None = None,
    ) -> SubDomainsResponse:
        request = GetSubDomainsRequest.from_selector(domain=domain, domains=domains)
        payload = self.request_json(
            "GET", REST_SUB_DOMAINS_PATH, fields=request.to_query_params()
        )
        return SubDomainsResponse.from_payload(payload)


class MCPClient(_SyncHTTPClient):
    """Synchronous AnySearch MCP tools/call client."""

    _mcp_client = MCP_CLIENT

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
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            retries=retries,
            user_agent=user_agent,
            http=http,
        )
        self.ids = count(1)

    def call_tool(
        self,
        tool: ToolName | str | MCPArguments | MCPToolCall,
        arguments: Mapping[str, JsonValue] | None = None,
    ) -> MCPToolResult:
        tool_call = MCPToolCall.from_arguments(tool, arguments)
        request_id = next(self.ids)
        payload = self.request_json(
            "POST",
            MCP_PATH,
            tool_call.to_request(request_id).to_payload(),
        )
        return MCPToolResponse.from_payload(payload, expected_id=request_id)

    def search(
        self,
        query: SearchArguments | str | Mapping[str, Any],
        *,
        domain: Domain | str | None = None,
        sub_domain: str | None = None,
        sub_domain_params: Mapping[str, JsonValue] | None = None,
        max_results: int | None = None,
    ) -> str:
        args = SearchArguments.from_input(
            query,
            domain=domain,
            sub_domain=sub_domain,
            sub_domain_params=sub_domain_params,
            max_results=max_results,
        )
        return self.call_tool(args).text

    def batch_search(
        self,
        queries: Sequence[SearchArgumentInput] | BatchSearchArguments,
        *,
        domain: Domain | str | None = None,
        sub_domain: str | None = None,
        sub_domain_params: Mapping[str, JsonValue] | None = None,
    ) -> str:
        args = BatchSearchArguments.from_queries(
            queries,
            domain=domain,
            sub_domain=sub_domain,
            sub_domain_params=sub_domain_params,
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

    def score(
        self,
        feedbacks: ScoreArguments | Sequence[ScoreFeedback | Mapping[str, Any]],
    ) -> str:
        return self.call_tool(ScoreArguments.from_feedbacks(feedbacks)).text


class AsyncClient(_AsyncHTTPClient):
    """Asynchronous AnySearch REST API client."""

    async def search(
        self,
        query: SearchRequest | str,
        *,
        max_results: int | None = None,
        tag: SearchTag | str | None = None,
        zone: Zone | str | None = None,
        language: str | None = None,
        params: Mapping[str, JsonValue] | None = None,
        output_format: OutputFormat | str | None = None,
    ) -> SearchResponse:
        search_request = SearchRequest.from_input(
            query,
            max_results=max_results,
            tag=tag,
            zone=zone,
            language=language,
            params=params,
            output_format=output_format,
        )
        payload = await self.request_json(
            "POST", REST_SEARCH_PATH, search_request.to_payload()
        )
        return SearchResponse.from_payload(payload)

    async def extract(self, url: ExtractRequest | str) -> ExtractResponse:
        request = (
            url if isinstance(url, ExtractRequest) else ExtractRequest.from_url(url)
        )
        payload = await self.request_json(
            "POST", REST_EXTRACT_PATH, request.to_payload()
        )
        return ExtractResponse.from_payload(payload)

    async def get_sub_domains(
        self,
        *,
        domain: Domain | str | None = None,
        domains: Sequence[Domain | str] | None = None,
    ) -> SubDomainsResponse:
        request = GetSubDomainsRequest.from_selector(domain=domain, domains=domains)
        payload = await self.request_json(
            "GET", REST_SUB_DOMAINS_PATH, fields=request.to_query_params()
        )
        return SubDomainsResponse.from_payload(payload)


class AsyncMCPClient(_AsyncHTTPClient):
    """Asynchronous AnySearch MCP tools/call client."""

    _mcp_client = MCP_CLIENT

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
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            retries=retries,
            user_agent=user_agent,
            http=http,
        )
        self.ids = count(1)

    async def call_tool(
        self,
        tool: ToolName | str | MCPArguments | MCPToolCall,
        arguments: Mapping[str, JsonValue] | None = None,
    ) -> MCPToolResult:
        tool_call = MCPToolCall.from_arguments(tool, arguments)
        request_id = next(self.ids)
        payload = await self.request_json(
            "POST",
            MCP_PATH,
            tool_call.to_request(request_id).to_payload(),
        )
        return MCPToolResponse.from_payload(payload, expected_id=request_id)

    async def search(
        self,
        query: SearchArguments | str | Mapping[str, Any],
        *,
        domain: Domain | str | None = None,
        sub_domain: str | None = None,
        sub_domain_params: Mapping[str, JsonValue] | None = None,
        max_results: int | None = None,
    ) -> str:
        args = SearchArguments.from_input(
            query,
            domain=domain,
            sub_domain=sub_domain,
            sub_domain_params=sub_domain_params,
            max_results=max_results,
        )
        result = await self.call_tool(args)
        return result.text

    async def batch_search(
        self,
        queries: Sequence[SearchArgumentInput] | BatchSearchArguments,
        *,
        domain: Domain | str | None = None,
        sub_domain: str | None = None,
        sub_domain_params: Mapping[str, JsonValue] | None = None,
    ) -> str:
        args = BatchSearchArguments.from_queries(
            queries,
            domain=domain,
            sub_domain=sub_domain,
            sub_domain_params=sub_domain_params,
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

    async def score(
        self,
        feedbacks: ScoreArguments | Sequence[ScoreFeedback | Mapping[str, Any]],
    ) -> str:
        result = await self.call_tool(ScoreArguments.from_feedbacks(feedbacks))
        return result.text
