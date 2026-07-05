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
	@set -eu; \
	if ! command -v gh >/dev/null 2>&1; then \
		echo "error: gh CLI is not installed" >&2; exit 1; \
	fi; \
	if ! gh auth status >/dev/null 2>&1; then \
		echo "error: gh is not authenticated (run 'gh auth login')" >&2; exit 1; \
	fi; \
	branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" != "main" ]; then \
		echo "error: release must be run from main (current branch: $$branch)" >&2; exit 1; \
	fi; \
	if [ -n "$$(git status --porcelain)" ]; then \
		echo "error: working tree has uncommitted changes; commit or stash first" >&2; exit 1; \
	fi; \
	git fetch origin main --quiet; \
	local_sha=$$(git rev-parse HEAD); \
	remote_sha=$$(git rev-parse origin/main); \
	if [ "$$local_sha" != "$$remote_sha" ]; then \
		echo "error: local main ($$local_sha) is out of sync with origin/main ($$remote_sha); pull first" >&2; exit 1; \
	fi; \
	version=$$(sed -nE 's/^version = "([^"]*)"$$/\1/p' pyproject.toml | head -n1); \
	if [ -z "$$version" ]; then echo "error: could not read version from pyproject.toml" >&2; exit 1; fi; \
	tag="v$$version"; \
	notes_file=$$(mktemp); \
	msg_file=$$(mktemp); \
	trap 'rm -f "$$notes_file" "$$msg_file"' EXIT; \
	awk -v ver="$$version" ' \
		/^## \[/ { if (found) exit; if (index($$0, "[" ver "]")) { found=1; next } else { next } } \
		found { print } \
	' CHANGELOG.md > "$$notes_file"; \
	if [ ! -s "$$notes_file" ]; then \
		echo "error: no CHANGELOG.md entry found for version $$version (tag $$tag)" >&2; exit 1; \
	fi; \
	git ls-remote --exit-code --tags origin "refs/tags/$$tag" >/dev/null 2>&1 && remote_check=0 || remote_check=$$?; \
	if [ "$$remote_check" -ne 0 ] && [ "$$remote_check" -ne 2 ]; then \
		echo "error: could not verify whether tag $$tag exists on origin (git ls-remote exited $$remote_check)" >&2; exit 1; \
	fi; \
	if [ "$$remote_check" -eq 0 ]; then \
		git fetch origin "refs/tags/$$tag:refs/tags/$$tag" --quiet --force; \
		existing_commit=$$(git rev-parse "refs/tags/$$tag^{commit}"); \
		if [ "$$existing_commit" != "$$local_sha" ]; then \
			echo "error: tag $$tag already exists on origin but points at $$existing_commit, not the current main ($$local_sha)" >&2; exit 1; \
		fi; \
		if gh release view "$$tag" >/dev/null 2>&1; then \
			echo "$$tag already exists with a published release; nothing to do."; \
			exit 0; \
		fi; \
		echo "Tag $$tag already exists on origin at the current commit but has no release -- publishing the release only."; \
	else \
		git tag -d "$$tag" >/dev/null 2>&1 || true; \
		{ echo "$$tag"; echo; cat "$$notes_file"; } > "$$msg_file"; \
		echo "Tagging and publishing $$tag..."; \
		git tag -a "$$tag" --cleanup=verbatim -F "$$msg_file"; \
		git push origin "$$tag"; \
	fi; \
	gh release create "$$tag" --title "$$tag" --notes-file "$$notes_file"
