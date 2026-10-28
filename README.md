# anysearch-py

Typed Python clients for AnySearch.

`Client` and `AsyncClient` call the REST Web API.
`MCPClient` and `AsyncMCPClient` call the remote MCP `tools/call` API.
All clients share Pydantic models, validation, and serialization logic.

| API | Methods |
| --- | --- |
| REST | `search`, `extract`, `get_sub_domains` |
| MCP | `search`, `batch_search`, `extract`, `get_sub_domains`, `score`, `call_tool` |

The API key is optional when the AnySearch endpoint permits anonymous access.

Requires Python 3.14 or newer.
Contracts were checked against the [official REST documentation](https://www.anysearch.com/docs/api-endpoints), the live domain directory, and MCP `tools/list` on 2026-10-28.

## Install

```bash
uv add anysearch-py
```

## REST Search

```python
from anysearch_py import Client, SearchTag

with Client(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    response = client.search(
        "Python 3.15 new features",
        tag=SearchTag.CODE_DOC,
        params={"library": "python"},
    )

print(response.data.results[0].url)
```

`max_results` must be an integer from 1 to 10.
Result titles may be empty, and `snippet` and `content` may be `None` when unavailable.
`output_format="markdown"` puts Markdown in result content; the response remains a typed JSON envelope.

## REST Domain Discovery

Discover current tags and their parameter definitions before choosing a vertical search.

```python
from anysearch_py import Client, Domain

with Client(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    response = client.get_sub_domains(domains=[Domain.CODE, Domain.FINANCE])

for domain in response.data.domains:
    for capability in domain.sub_domains:
        print(capability.sub_domain, capability.params)
```

The SDK sends repeated `domain` query parameters for multiple domains.
Unknown REST domains can fail when the service cannot resolve their capabilities.
REST search accepts discovered `domain.sub_domain` strings as well as `SearchTag` values.

## REST Extraction

```python
from anysearch_py import Client

with Client(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    response = client.extract("https://example.com")

print(response.data.title)
print(response.data.content)
```

Extraction supports HTML, plain text, JSON, and Markdown from public HTTP or HTTPS URLs.
See the [extract endpoint](https://www.anysearch.com/docs/api-endpoints/v1-extract) for request limits and errors.

## Async REST Search

```python
import asyncio

from anysearch_py import AsyncClient


async def main() -> None:
    async with AsyncClient(api_key="YOUR_ANYSEARCH_API_KEY") as client:
        response = await client.search("Python 3.15 new features")

    print(response.data.results[0].url)


asyncio.run(main())
```

`AsyncClient.extract` and `AsyncClient.get_sub_domains` use the same arguments and response models as their synchronous counterparts.

## MCP Tools

```python
from anysearch_py import Domain, MCPClient

with MCPClient(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    markdown = client.get_sub_domains(domains=[Domain.FINANCE, Domain.HEALTH])

print(markdown)
```

## MCP Search

```python
from anysearch_py import MCPClient

with MCPClient(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    markdown = client.search("Python 3.15 new features", max_results=5)

print(markdown)
```

## MCP Metadata and Feedback

Use `call_tool` to retain structured content and metadata alongside text.
`structured_content` exposes `structuredContent`, and `meta` exposes `_meta`.
Search metadata contains `request_id`; batch search metadata contains `request_ids`, one per query.

```python
from anysearch_py import MCPClient, ScoreFeedback, SearchArguments

with MCPClient(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    result = client.call_tool(SearchArguments(query="Python 3.15 new features"))
    print(result.text)

    request_id = (result.meta or {}).get("request_id")
    if isinstance(request_id, str):
        client.score([ScoreFeedback(request_id=request_id, score=4)])
```

Choose the score after reviewing the results: 1 means unusable, 5 means fully answered.
`score` accepts 1–10 feedback entries with integer scores from 1 to 5 and request IDs up to 64 characters.
Feedback submission acknowledges queuing, not persistence.
`AsyncMCPClient` provides the same methods as awaitable calls.

## Errors

Non-success HTTP responses raise `HTTPStatusError`, exposing `status`, `code`, `error_code`, `request_id`, `data`, and `headers`.
REST errors inside an HTTP 200 response raise `APIError` with the same business error fields.
MCP errors raise `JSONRPCError`; invalid JSON and unexpected response schemas raise `ResponseDecodeError` and `ResponseValidationError`.

HTTP 402 messages can contain generated account credentials, so treat their messages as secrets and avoid logging them.
The SDK retries connection failures only; it does not automatically replay requests after HTTP errors or read timeouts.

## Catalog Changes

The current catalog uses `ACADEMIC_PAPER`, `ACADEMIC_PERSON`, `LEGAL_ENFORCEMENT`, and `LEGAL_JUDICIAL`.
The former `ACADEMIC_BIOMEDICAL`, `ACADEMIC_PREPRINT`, `ACADEMIC_SEARCH`, `LEGAL_CASE`, and `LEGAL_STATUTE` enum members were removed.
Use `get_sub_domains` to choose the capability matching your query.

## Tests

```bash
just check
uv run pytest --cov=anysearch_py --cov-report=term-missing
```

The default suite runs without credentials or internet access.
It uses `pytest-httpserver` to exercise real HTTP connections for all four clients, recorded service responses for schema checks, and Hypothesis for nested JSON serialization.
Both anonymous and authenticated request headers are checked locally.
The coverage gate requires at least 95% combined statement and branch coverage.

Run the public service tests explicitly:

```bash
uv run pytest tests/test_live.py --live=anonymous
uv run pytest tests/test_live.py --live=authenticated
uv run pytest tests/test_live.py --live=all
```

Each mode covers synchronous and asynchronous clients, REST and MCP methods, server validation, and invalid credentials.
Authenticated tests read `ANYSEARCH_API_KEY` from the environment first, then the project `.env` through `python-dotenv`.
Requesting authenticated tests without a key is a configuration error.
Package code never reads `.env`.

Live tests consume service quota and submit score feedback for successful test searches.
They require public AnySearch and GitHub raw content access; upstream errors fail the run.
Pytest failure reports redact the configured key and generated account credentials.
Captured responses and their provenance are documented in [tests/fixtures/README.md](tests/fixtures/README.md).
