# Cloud variant

A fork of [software-factory-claude-code-v2](../software-factory-claude-code-v2)
that runs inside a Claude Code cloud session. Same pipeline, same agents, same
state files. GPLv3, like the original.

## Why it exists

`gh issue ...` and `gh pr ...` use GitHub's GraphQL API, which cloud sessions
don't allow, and a cloud session doesn't merge pull requests on its own. The
original factory stops at its first step there.

## What changed

| File | Change |
|---|---|
| `factory/bin/ghx` | New. Accepts the `gh` commands the factory uses and answers them over REST (`gh api`), or hands them to `gh` unchanged. |
| `factory/bin/job` | Calls `ghx` instead of `gh`. With `auto_merge` off, an approved job is synced, gated, marked ready and left for a person to merge. |
| `factory/config.json` | New keys `github_transport` (`rest`) and `auto_merge` (`false`). `concurrency` is 1. |
| `.claude/agents/builder.md`, `.claude/skills/factory/SKILL.md`, `.claude/agents/approver.md` | Use `factory/bin/ghx`; describe the no-merge ending. |
| `INSTALL.md` | Copies `ghx`; points at this folder; explains the two keys. |

## What an approved job looks like

The PR is ready for review, a comment says the factory approved it, and the
issue carries `factory:needs-human`. Merge the PR on GitHub. The next
`/factory run` sees the merge and marks the job done.

## Limits

- Marking a draft PR ready uses a route that exists only in cloud sessions. On
  a laptop set `github_transport` to `gh`.
- Not yet run end to end on a real issue. The GitHub layer was tested against a
  real repository: reading issues and pull requests, and adding and removing a
  label.
