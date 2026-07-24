PYTHON ?= python3

.PHONY: validate test lint typecheck container-build

validate:
	uv run nebula validate examples/valid/minimal-project

preview:
	uv run nebula preview examples/valid/minimal-project --output /tmp/nebulamaster-preview.png --force

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy .

container-build:
	docker build -f apps/renderer-cli/Dockerfile -t nebula-renderer-cli .
