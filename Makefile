.PHONY: install dev gates

install:            ## Install `turiya` on PATH (pinned snapshot)
	uv tool install . --reinstall

dev:                ## Sync the dev environment
	uv sync --all-extras --dev

gates:              ## Run all required gates
	uv run pytest
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src tests
	uv run ty check
