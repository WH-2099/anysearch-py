# anysearch-py

Typed Python clients for AnySearch.

The package has two first-class clients.

`Client` calls the REST Web API.

`MCPClient` calls the remote MCP `tools/call` API.

Both clients share the same Pydantic models, enums, validation, and serialization logic.

The API key is optional when the AnySearch endpoint permits anonymous access.

## Install

```bash
uv add anysearch-py
```

## REST Search

```python
from anysearch_py import Client, SearchTag

with Client(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    response = client.search(
        "Go 1.26 release notes",
        tag=SearchTag.CODE_DOC,
        params={"library": "golang"},
    )

print(response.data.results[0].url)
```

## Async REST Search

```python
import asyncio

from anysearch_py import AsyncClient


async def main() -> None:
    async with AsyncClient(api_key="YOUR_ANYSEARCH_API_KEY") as client:
        response = await client.search("what is quantum computing")

    print(response.data.results[0].url)


asyncio.run(main())
```

## MCP Tools

```python
from anysearch_py import Domain, MCPClient

with MCPClient(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    markdown = client.get_sub_domains(domains=[Domain.FINANCE, Domain.HEALTH])

print(markdown)
```

## MCP Search

```python
from anysearch_py import Domain, MCPClient

with MCPClient(api_key="YOUR_ANYSEARCH_API_KEY") as client:
    markdown = client.search(
        "AAPL",
        domain=Domain.FINANCE,
        sub_domain="finance.quote",
        sub_domain_params={
            "type": "stock",
            "symbol": "AAPL",
            "cn_code": "",
        },
        max_results=5,
    )

print(markdown)
```

## Live Tests

Live tests read `ANYSEARCH_API_KEY` from the environment first, then `.env`.

If neither source provides a non-empty value, those tests skip automatically.

Package code never reads `.env`.
