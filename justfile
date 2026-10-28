default:
    @just --list

dev:
    uv sync
    uv run prek install

format:
    uv run ruff format

lint: format
    uv run ruff check --fix

tc: lint
    uv run ty check src tests

test: tc
    uv run pytest --cov=anysearch_py

check:
    uv lock --check
    uv run ruff format --check
    uv run ruff check
    uv run ty check src tests
    uv run pytest --cov=anysearch_py

build: check
    uv build --no-create-gitignore --no-sources

clean:
    fd -H -t d '^__pycache__$' -x rm -rf
    rm -rf dist/ .pytest_cache/ .ruff_cache/
    uv run ruff clean
