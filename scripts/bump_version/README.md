# bump_version

Interactive CLI tool for version bumping and release automation.

## Setup

```bash
cd scripts/bump_version
uv sync
```

## Usage

### Interactive Mode (default)

```bash
uv run bump_version.py
```

This will:
1. Show current version and recent commits
2. Let you select bump type (patch/minor/major)
3. Ask for confirmation
4. Update `pyproject.toml`, create tag, push, and create GitHub release

### Non-Interactive Mode

```bash
uv run bump_version.py --patch    # 0.65.0 -> 0.65.1
uv run bump_version.py --minor    # 0.65.0 -> 0.66.0
uv run bump_version.py --major    # 0.65.0 -> 1.0.0
```

### Options

| Flag | Description |
|------|-------------|
| `--patch` | Bump patch version (X.Y.Z -> X.Y.Z+1) |
| `--minor` | Bump minor version (X.Y.Z -> X.Y+1.0) |
| `--major` | Bump major version (X.Y.Z -> X+1.0.0) |
| `--dry-run` | Preview actions without executing |
| `--yes`, `-y` | Skip confirmation prompt |
| `--notes FILE` | Use custom release notes file |

### Examples

```bash
# Preview what would happen
uv run bump_version.py --patch --dry-run

# Bump patch version without confirmation
uv run bump_version.py --patch --yes

# Use custom release notes
uv run bump_version.py --minor --notes ../release_notes.md
```

## Requirements

- `gh` CLI installed and authenticated (`gh auth login`)
- Clean git working tree (no uncommitted changes)
- Should be on `main` branch (warning if not)

## What It Does

1. Reads current version from root `pyproject.toml`
2. Calculates new version based on bump type
3. Updates `pyproject.toml` with new version
4. Creates git commit: "Bump version to X.Y.Z"
5. Creates git tag: `vX.Y.Z`
6. Pushes to origin with tags
7. Creates GitHub release with auto-generated release notes
