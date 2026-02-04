# Release Automation Scripts

## scripts/release_flow.sh
Automates the end-to-end release flow:
1) Creates/merges a PR from a feature branch into `main`
2) Bumps the version in `pyproject.toml`, tags, pushes, and creates a GitHub release
3) Rebases the feature branch onto the updated `main`

Usage:
```bash
scripts/release_flow.sh -b <branch> -v <version> [-t "Release title"] [-n release_notes.md]
```

Requirements:
- `gh` CLI authenticated with repo scope
- `git` and `python3` available
- Clean working tree (no uncommitted changes)
- Branch should track its remote (run once: `git branch --set-upstream-to=origin/<branch> <branch>`)

Notes:
- If a PR already exists and is merged, the script skips the merge step.
- Version bump uses the provided `-v`; if you pass release notes via `-n`, they are used for the GitHub release.
- The branch is rebased on `main` at the end; force-push is used to update the remote branch.

## scripts/gen_release_notes.py
Generates a Markdown skeleton for release notes with a commit list.

Usage:
```bash
uv run python scripts/gen_release_notes.py --version 0.22.0 --output release_notes_0.22.0.md [--from-ref v0.21.0]
```

This file can be passed to `release_flow.sh` via `-n`.

## scripts/bump_version/

Interactive CLI tool for simplified version bumping. Unlike `release_flow.sh`, this tool focuses only on:
- Bumping version in `pyproject.toml`
- Creating git tag and pushing
- Creating GitHub release

It does NOT manage PRs or branch rebasing.

Setup and usage:
```bash
cd scripts/bump_version
uv sync
uv run bump_version.py              # Interactive mode
uv run bump_version.py --patch      # Non-interactive patch bump
uv run bump_version.py --dry-run    # Preview without executing
```

See `scripts/bump_version/README.md` for full documentation.
