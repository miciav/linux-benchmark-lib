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
