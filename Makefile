PYTHON ?= python3

.PHONY: validate preview test lint typecheck container-build package-desktop bump-version

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

package-desktop:
	./.venv/bin/python scripts/package_desktop.py

bump-version:
	@if [ -z "$(VERSION)" ]; then echo "Usage: make bump-version VERSION=0.2.0"; exit 1; fi
	$(PYTHON) scripts/bump_version.py $(VERSION)
