@AGENTS.md

# CLAUDE.md — turiya

Claude-only operating notes for this repo. The shared, tool-neutral guidance (project
purpose, file map, conventions, logging schema, what not to touch) lives in
[`AGENTS.md`](AGENTS.md), imported above; this file adds only what is specific to Claude
driving the work here.

## Project tracking

turiya has **no GitHub Project board**. Work is tracked as plain GitHub issues, so none of
the agent-driven board Status transitions used in the crusty repositories apply here. Do
not attempt a `gh project item-edit` against this repo.

## Review loop

The canonical Copilot review loop lives in `AGENTS.md` under "Copilot review". Two
turiya-specific notes:

- The `main-protection` ruleset carries a `copilot_code_review` rule with
  `review_on_push: true` (and `review_draft_pull_requests: true`), so a fresh review is
  auto-requested on every push — no manual re-request is normally needed. If a review
  seems stuck, check the ruleset before assuming the request was lost;
  `gh pr edit <n> --add-reviewer copilot-pull-request-reviewer` is the fallback.
- turiya has no coverage tooling yet, so the codecov ready-gate is inert. Treat "threads
  resolved + required checks green" as the bar until the coverage issue ships.
