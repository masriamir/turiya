.PHONY: install dev gates release

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

release: gates       ## Tag, push, and publish a GitHub release for the pyproject.toml version
	@version=$$(grep -m1 '^version = ' pyproject.toml | sed -E 's/version = "(.*)"/\1/'); \
	if [ -z "$$version" ]; then echo "error: could not read version from pyproject.toml" >&2; exit 1; fi; \
	tag="v$$version"; \
	if git rev-parse "$$tag" >/dev/null 2>&1; then \
		echo "error: tag $$tag already exists" >&2; exit 1; \
	fi; \
	notes_file=$$(mktemp); \
	awk -v ver="$$version" ' \
		/^## \[/ { if (found) exit; if (index($$0, "[" ver "]")) { found=1; next } else { next } } \
		found { print } \
	' CHANGELOG.md > "$$notes_file"; \
	if [ ! -s "$$notes_file" ]; then \
		echo "error: no CHANGELOG.md entry found for $$tag" >&2; rm -f "$$notes_file"; exit 1; \
	fi; \
	msg_file=$$(mktemp); \
	{ echo "$$tag"; echo; cat "$$notes_file"; } > "$$msg_file"; \
	echo "Tagging and publishing $$tag..."; \
	git tag -a "$$tag" --cleanup=verbatim -F "$$msg_file"; \
	git push origin "$$tag"; \
	gh release create "$$tag" --title "$$tag" --notes-file "$$notes_file"; \
	rm -f "$$notes_file" "$$msg_file"
