from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Iterator

import pytest
from pydantic import SecretStr
from pytest_httpserver import HTTPServer

from anysearch_py import AsyncClient, AsyncMCPClient, Client, MCPClient
from tests.support import AnyClient, load_api_key, opened_client, redact

LIVE_KEY = pytest.StashKey[SecretStr | None]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        choices=("anonymous", "authenticated", "all"),
        help="Run live AnySearch tests with anonymous access, an API key, or both.",
    )


def pytest_configure(config: pytest.Config) -> None:
    key = None
    if config.getoption("--live") in {"authenticated", "all"}:
        key = load_api_key(config.rootpath / ".env")
        if key is None:
            msg = (
                "--live=authenticated/all requires ANYSEARCH_API_KEY or a project .env"
            )
            raise pytest.UsageError(msg)
    config.stash[LIVE_KEY] = key


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    mode = config.getoption("--live")
    selected = []
    deselected = []
    for item in items:
        callspec = getattr(item, "callspec", None)
        auth = callspec.params.get("live_auth") if callspec is not None else None
        if item.get_closest_marker("live") and (
            mode is None or (auth is not None and mode not in {auth, "all"})
        ):
            deselected.append(item)
        else:
            selected.append(item)
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if item.get_closest_marker("live"):
        key = item.config.stash.get(LIVE_KEY, None)
        if report.longrepr is not None:
            report.longrepr = redact(str(report.longrepr), key)
        report.sections = [(name, redact(text, key)) for name, text in report.sections]
    return report


@pytest.fixture
def server(httpserver: HTTPServer) -> Iterator[HTTPServer]:
    yield httpserver
    httpserver.check()


@pytest.fixture(params=[None, "local-test-api-key"], ids=["anonymous", "authenticated"])
def api_key(request: pytest.FixtureRequest) -> str | None:
    return request.param


@pytest.fixture(params=[Client, AsyncClient], ids=["sync", "async"])
async def rest_client(
    request: pytest.FixtureRequest, server: HTTPServer, api_key: str | None
) -> AsyncIterator[Client | AsyncClient]:
    async with opened_client(
        request.param(base_url=server.url_for("/"), api_key=api_key)
    ) as client:
        yield client


@pytest.fixture(params=[MCPClient, AsyncMCPClient], ids=["sync", "async"])
async def mcp_client(
    request: pytest.FixtureRequest, server: HTTPServer, api_key: str | None
) -> AsyncIterator[MCPClient | AsyncMCPClient]:
    async with opened_client(
        request.param(base_url=server.url_for("/"), api_key=api_key)
    ) as client:
        yield client


@pytest.fixture(
    params=[Client, AsyncClient, MCPClient, AsyncMCPClient],
    ids=["rest-sync", "rest-async", "mcp-sync", "mcp-async"],
)
async def transport_client(
    request: pytest.FixtureRequest, server: HTTPServer, api_key: str | None
) -> AsyncIterator[AnyClient]:
    async with opened_client(
        request.param(base_url=server.url_for("/"), api_key=api_key)
    ) as client:
        yield client


@pytest.fixture(params=["anonymous", "authenticated"])
def live_auth(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def live_api_key(request: pytest.FixtureRequest, live_auth: str) -> SecretStr | None:
    return request.config.stash[LIVE_KEY] if live_auth == "authenticated" else None


@pytest.fixture(params=[Client, AsyncClient], ids=["sync", "async"])
async def live_rest_client(
    request: pytest.FixtureRequest, live_api_key: SecretStr | None
) -> AsyncIterator[Client | AsyncClient]:
    async with opened_client(
        request.param(api_key=live_api_key.get_secret_value() if live_api_key else None)
    ) as client:
        yield client


@pytest.fixture(params=[MCPClient, AsyncMCPClient], ids=["sync", "async"])
async def live_mcp_client(
    request: pytest.FixtureRequest, live_api_key: SecretStr | None
) -> AsyncIterator[MCPClient | AsyncMCPClient]:
    async with opened_client(
        request.param(api_key=live_api_key.get_secret_value() if live_api_key else None)
    ) as client:
        yield client
