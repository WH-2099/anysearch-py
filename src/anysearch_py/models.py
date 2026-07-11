"""Pydantic models shared by the AnySearch REST and MCP clients."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    computed_field,
    model_validator,
)

from .exceptions import APIError, JSONRPCError, ResponseValidationError

type JsonScalar = StrictStr | StrictInt | StrictFloat | StrictBool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type SearchArgumentInput = SearchArguments | str | Mapping[str, Any]

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SubDomainName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
    ),
]

_JSON_VALUE = TypeAdapter(JsonValue)


class StrictRequestModel(BaseModel):
    """Base class for outbound payloads."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_default=True,
        allow_inf_nan=False,
    )

    def to_payload(self) -> JsonObject:
        dumped = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        if not isinstance(dumped, dict):
            msg = "model dump did not produce a JSON object"
            raise TypeError(msg)
        return dumped


class ResponseModel(BaseModel):
    """Base class for inbound payloads."""

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        populate_by_name=True,
        validate_default=True,
    )


class Domain(StrEnum):
    ACADEMIC = "academic"
    AGRICULTURE = "agriculture"
    BUSINESS = "business"
    CODE = "code"
    ENERGY = "energy"
    ENVIRONMENT = "environment"
    FILM = "film"
    FINANCE = "finance"
    GAMING = "gaming"
    GENERAL = "general"
    HEALTH = "health"
    IP = "ip"
    LEGAL = "legal"
    RESOURCE = "resource"
    SECURITY = "security"
    SOCIAL_MEDIA = "social_media"
    TRAVEL = "travel"


class SearchTag(StrEnum):
    ACADEMIC_BIOMEDICAL = "academic.biomedical"
    ACADEMIC_CITATION = "academic.citation"
    ACADEMIC_DATASET = "academic.dataset"
    ACADEMIC_PREPRINT = "academic.preprint"
    ACADEMIC_SEARCH = "academic.search"
    AGRICULTURE_FAO = "agriculture.fao"
    BUSINESS_COMPANY = "business.company"
    BUSINESS_JOBS = "business.jobs"
    BUSINESS_PEOPLE = "business.people"
    BUSINESS_TRADE = "business.trade"
    CODE_DOC = "code.doc"
    CODE_SNIPPET = "code.snippet"
    ENERGY_ELECTRICITY = "energy.electricity"
    ENERGY_PRODUCTION = "energy.production"
    ENVIRONMENT_AQI = "environment.aqi"
    FILM_TORRENT = "film.torrent"
    FINANCE_CALENDAR = "finance.calendar"
    FINANCE_FUNDAMENTAL = "finance.fundamental"
    FINANCE_MACRO = "finance.macro"
    FINANCE_NEWS = "finance.news"
    FINANCE_QUOTE = "finance.quote"
    FINANCE_SCREEN = "finance.screen"
    GAMING_ESPORTS = "gaming.esports"
    GAMING_STORE = "gaming.store"
    GENERAL_GENERAL = "general.general"
    HEALTH_DRUG = "health.drug"
    HEALTH_STATS = "health.stats"
    HEALTH_TRIAL = "health.trial"
    IP_GLOBAL = "ip.global"
    LEGAL_CASE = "legal.case"
    LEGAL_LEGISLATION = "legal.legislation"
    LEGAL_STATUTE = "legal.statute"
    RESOURCE_IMAGE = "resource.image"
    SECURITY_INTEL = "security.intel"
    SECURITY_NOISE = "security.noise"
    SECURITY_SCAN = "security.scan"
    SECURITY_VULN = "security.vuln"
    SOCIAL_MEDIA_SOCIAL_MEDIA = "social_media.social_media"
    TRAVEL_FLIGHT = "travel.flight"
    TRAVEL_FLIGHT_STATUS = "travel.flight_status"


class Zone(StrEnum):
    CHINA = "cn"
    INTERNATIONAL = "intl"


class OutputFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"


class ToolName(StrEnum):
    SEARCH = "search"
    BATCH_SEARCH = "batch_search"
    GET_SUB_DOMAINS = "get_sub_domains"
    EXTRACT = "extract"


class SearchRequest(StrictRequestModel):
    """REST /v1/search request."""

    query: NonEmptyString
    max_results: StrictInt = Field(default=10, ge=1, le=20)
    tag: SearchTag | None = None
    zone: Zone | None = None
    language: NonEmptyString | None = None
    params: JsonObject | None = None
    format: OutputFormat = OutputFormat.JSON

    @classmethod
    def from_input(
        cls,
        query: Self | str,
        *,
        max_results: int | None = None,
        tag: SearchTag | str | None = None,
        zone: Zone | str | None = None,
        language: str | None = None,
        params: Mapping[str, JsonValue] | None = None,
        output_format: OutputFormat | str | None = None,
    ) -> Self:
        modifiers = {
            key: value
            for key, value in {
                "max_results": max_results,
                "tag": tag,
                "zone": zone,
                "language": language,
                "params": dict(params) if params is not None else None,
                "format": output_format,
            }.items()
            if value is not None
        }
        if isinstance(query, SearchRequest):
            if modifiers:
                msg = "keyword arguments cannot be combined with SearchRequest"
                raise ValueError(msg)
            return query
        return cls.model_validate({"query": query, **modifiers})


class SearchResult(ResponseModel):
    """One REST search result."""

    title: str
    url: HttpUrl
    snippet: str
    content: str | None = None


class SearchMetadata(ResponseModel):
    """REST search metadata."""

    total_results: StrictInt = Field(ge=0)
    search_time_ms: StrictInt = Field(ge=0)


class SearchData(ResponseModel):
    """REST search data envelope."""

    results: tuple[SearchResult, ...]
    metadata: SearchMetadata


class APIErrorDetails(ResponseModel):
    """Normalized application error details."""

    message: str
    code: int | str | None = None
    request_id: str | None = None
    data: JsonValue | None = None

    @classmethod
    def from_payload(cls, payload: Any, *, fallback_message: str) -> Self:
        if not isinstance(payload, dict):
            return cls(
                message=fallback_message,
                data=cls.coerce_json(payload),
            )

        code = payload.get("code")
        if not isinstance(code, int | str):
            code = payload.get("symbol")
        if not isinstance(code, int | str):
            code = None

        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            message = payload.get("error")
        if not isinstance(message, str) or not message.strip():
            message = fallback_message

        request_id = payload.get("request_id")
        if not isinstance(request_id, str):
            request_id = None

        return cls(
            message=message,
            code=code,
            request_id=request_id,
            data=cls.coerce_json(payload.get("data")),
        )

    @staticmethod
    def coerce_json(value: Any) -> JsonValue:
        try:
            return _JSON_VALUE.validate_python(value)
        except ValidationError:
            if isinstance(value, bytes):
                try:
                    return value.decode()
                except UnicodeDecodeError:
                    pass
            return str(value)


class APIEnvelope[DataT](ResponseModel):
    """Standard REST response envelope."""

    code: StrictInt
    message: str
    request_id: str | None = None
    data: DataT | None = None

    @computed_field
    @property
    def ok(self) -> bool:
        return self.code == 0

    def raise_if_error(self) -> None:
        if self.ok:
            return

        raise APIError(
            self.message or "AnySearch request failed",
            code=self.code,
            request_id=self.request_id,
            data=APIErrorDetails.coerce_json(self.data),
        )


class SearchResponse(APIEnvelope[SearchData]):
    """Successful REST search response."""

    data: SearchData

    @classmethod
    def from_payload(cls, payload: Any) -> Self:
        try:
            APIEnvelope[Any].model_validate(payload).raise_if_error()
        except ValidationError as exc:
            msg = "search response does not match the AnySearch envelope schema"
            raise ResponseValidationError(msg, payload=payload) from exc

        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            msg = "successful search response does not match the documented schema"
            raise ResponseValidationError(msg, payload=payload) from exc


class MCPArguments(StrictRequestModel):
    """Base class for MCP tool arguments."""

    tool_name: ClassVar[ToolName]

    def to_tool_call(self) -> MCPToolCall:
        return MCPToolCall(name=self.tool_name, arguments=self.to_payload())


class SearchArguments(MCPArguments):
    """MCP search tool arguments."""

    tool_name = ToolName.SEARCH

    query: NonEmptyString
    domain: Domain | None = None
    sub_domain: SubDomainName | None = None
    sub_domain_params: JsonObject | None = None
    max_results: StrictInt | None = Field(default=None, ge=1, le=10)

    @classmethod
    def from_input(
        cls, arguments: SearchArguments | str | Mapping[str, Any], **kwargs: Any
    ) -> SearchArguments:
        if isinstance(arguments, SearchArguments):
            if kwargs:
                msg = "keyword arguments cannot be combined with SearchArguments"
                raise ValueError(msg)
            return arguments
        if isinstance(arguments, str):
            return cls.model_validate({"query": arguments, **kwargs})
        return cls.model_validate({**dict(arguments), **kwargs})

    @model_validator(mode="after")
    def validate_vertical_shape(self) -> Self:
        if self.domain is None:
            if self.sub_domain is not None or self.sub_domain_params is not None:
                msg = "sub_domain and sub_domain_params require domain"
                raise ValueError(msg)
            return self
        if self.sub_domain is None:
            msg = "sub_domain is required when domain is provided"
            raise ValueError(msg)
        return self


class BatchSearchArguments(MCPArguments):
    """MCP batch_search tool arguments."""

    tool_name = ToolName.BATCH_SEARCH

    queries: tuple[SearchArguments, ...] = Field(min_length=1, max_length=5)

    @classmethod
    def from_queries(
        cls,
        queries: BatchSearchArguments | Sequence[SearchArgumentInput],
        *,
        domain: Domain | str | None = None,
        sub_domain: str | None = None,
        sub_domain_params: Mapping[str, JsonValue] | None = None,
    ) -> BatchSearchArguments:
        if isinstance(queries, BatchSearchArguments):
            if any(
                value is not None for value in (domain, sub_domain, sub_domain_params)
            ):
                msg = "shared arguments cannot be combined with BatchSearchArguments"
                raise ValueError(msg)
            return queries
        if isinstance(queries, str):
            msg = "queries must be a sequence, not a string"
            raise TypeError(msg)

        shared_params = (
            dict(sub_domain_params) if sub_domain_params is not None else None
        )
        items: list[SearchArguments] = []
        for query in queries:
            values: dict[str, Any]
            if isinstance(query, SearchArguments):
                values = query.to_payload()
            elif isinstance(query, str):
                values = {"query": query}
            else:
                values = dict(query)

            if domain is not None and values.get("domain") is None:
                values["domain"] = str(domain)
            if sub_domain is not None and values.get("sub_domain") is None:
                values["sub_domain"] = sub_domain
            if shared_params is not None and values.get("sub_domain_params") is None:
                values["sub_domain_params"] = shared_params
            items.append(SearchArguments.model_validate(values))
        return cls(queries=tuple(items))


class GetSubDomainsArguments(MCPArguments):
    """MCP get_sub_domains tool arguments."""

    tool_name = ToolName.GET_SUB_DOMAINS

    domain: Domain | None = None
    domains: tuple[Domain, ...] | None = Field(default=None, min_length=1, max_length=5)

    @classmethod
    def from_selector(
        cls,
        *,
        domain: Domain | str | None = None,
        domains: Sequence[Domain | str] | None = None,
    ) -> Self:
        if isinstance(domains, str):
            msg = "domains must be a sequence, not a string"
            raise TypeError(msg)
        return cls.model_validate(
            {
                "domain": domain,
                "domains": tuple(domains) if domains is not None else None,
            },
        )

    @model_validator(mode="after")
    def validate_domain_selector(self) -> Self:
        has_domain = self.domain is not None
        has_domains = self.domains is not None
        if has_domain == has_domains:
            msg = "provide exactly one of domain or domains"
            raise ValueError(msg)
        return self


class ExtractArguments(MCPArguments):
    """MCP extract tool arguments."""

    tool_name = ToolName.EXTRACT

    url: HttpUrl

    @classmethod
    def from_url(cls, url: str) -> Self:
        return cls.model_validate({"url": url})


class MCPContentBlock(ResponseModel):
    """One MCP content block."""

    type: str
    text: str | None = None

    @model_validator(mode="after")
    def validate_text_block(self) -> Self:
        if self.type == "text" and self.text is None:
            msg = "MCP text content must include text"
            raise ValueError(msg)
        return self


class MCPToolResult(ResponseModel):
    """MCP tools/call result."""

    content: tuple[MCPContentBlock, ...]
    is_error: StrictBool = Field(default=False, alias="isError")

    @computed_field
    @property
    def text(self) -> str:
        return "\n".join(
            block.text for block in self.content if block.type == "text" and block.text
        )

    def raise_if_error(self) -> None:
        if not self.is_error:
            return

        raise JSONRPCError(self.text or "MCP tool returned an error")


class JSONRPCErrorObject(ResponseModel):
    code: StrictInt
    message: str
    data: JsonValue | None = None

    def raise_error(self) -> None:
        raise JSONRPCError(self.message, code=self.code, data=self.data)


class JSONRPCResponse[DataT](ResponseModel):
    jsonrpc: Literal["2.0"]
    id: StrictInt | StrictStr
    result: DataT | None = None
    error: JSONRPCErrorObject | None = None

    @model_validator(mode="after")
    def validate_result_or_error(self) -> Self:
        if ("result" in self.model_fields_set) == ("error" in self.model_fields_set):
            msg = "JSON-RPC response must contain exactly one of result or error"
            raise ValueError(msg)
        return self

    def unwrap(self) -> DataT:
        if self.error is not None:
            self.error.raise_error()
        if self.result is None:
            msg = "MCP response is missing result"
            raise ResponseValidationError(msg, payload=self.model_dump(mode="json"))
        return self.result


class MCPToolResponse(JSONRPCResponse[MCPToolResult]):
    """Successful MCP tools/call response."""

    @classmethod
    def from_payload(
        cls,
        payload: Any,
        *,
        expected_id: int | str | None = None,
    ) -> MCPToolResult:
        try:
            response = cls.model_validate(payload)
        except ValidationError as exc:
            msg = "MCP response does not match JSON-RPC tools/call schema"
            raise ResponseValidationError(msg, payload=payload) from exc
        if expected_id is not None and response.id != expected_id:
            msg = "MCP response id does not match request id"
            raise ResponseValidationError(msg, payload=payload)
        result = response.unwrap()
        result.raise_if_error()
        return result


class JSONRPCToolCallParams(StrictRequestModel):
    name: ToolName
    arguments: JsonObject


class JSONRPCToolCallRequest(StrictRequestModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: StrictInt
    method: Literal["tools/call"] = "tools/call"
    params: JSONRPCToolCallParams


class MCPToolCall(StrictRequestModel):
    """MCP tool call before JSON-RPC wrapping."""

    name: ToolName
    arguments: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_arguments(
        cls,
        tool: ToolName | str | MCPArguments | MCPToolCall,
        arguments: Mapping[str, JsonValue] | None = None,
    ) -> MCPToolCall:
        if isinstance(tool, MCPToolCall | MCPArguments):
            if arguments is not None:
                msg = "arguments cannot be combined with a pre-built tool call"
                raise ValueError(msg)
            return tool if isinstance(tool, MCPToolCall) else tool.to_tool_call()
        if isinstance(arguments, MCPArguments):
            msg = "pass MCPArguments as the first argument"
            raise TypeError(msg)
        return cls.model_validate(
            {
                "name": tool,
                "arguments": dict(arguments) if arguments is not None else {},
            },
        )

    def to_request(self, request_id: int) -> JSONRPCToolCallRequest:
        return JSONRPCToolCallRequest(
            id=request_id,
            params=JSONRPCToolCallParams(
                name=self.name,
                arguments=self.arguments,
            ),
        )
