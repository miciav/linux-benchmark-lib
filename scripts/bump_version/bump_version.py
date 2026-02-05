#!/usr/bin/env python3
"""
Version bump and release automation for linux-benchmark-lib.

Interactive usage:
    uv run bump_version.py

Non-interactive usage:
    uv run bump_version.py --patch [--dry-run] [--yes] [--notes FILE]
    uv run bump_version.py --minor [--dry-run] [--yes] [--notes FILE]
    uv run bump_version.py --major [--dry-run] [--yes] [--notes FILE]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

import questionary
from questionary import Style

# Custom style for questionary
CUSTOM_STYLE = Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:cyan bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:cyan"),
    ]
)

BumpType = Literal["patch", "minor", "major"]


def find_repo_root() -> Path:
    """Find the git repository root (parent of scripts/bump_version)."""
    # We're in scripts/bump_version/, so go up two levels
    return Path(__file__).resolve().parent.parent.parent


def get_current_version(repo_root: Path) -> str:
    """Read current version from pyproject.toml."""
    pyproject = repo_root / "pyproject.toml"
    text = pyproject.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)


def bump_version(version: str, bump_type: BumpType) -> str:
    """Calculate new version based on bump type."""
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {version}")

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:  # patch
        return f"{major}.{minor}.{patch + 1}"


def get_last_tag() -> str | None:
    """Get the most recent git tag."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_commits_since_tag(tag: str | None) -> list[str]:
    """Get list of commits since the given tag."""
    if tag:
        range_spec = f"{tag}..HEAD"
    else:
        range_spec = "HEAD"

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--no-merges", range_spec],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def get_current_branch() -> str:
    """Get current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def is_working_tree_clean() -> bool:
    """Check if git working tree is clean."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return not result.stdout.strip()


def check_gh_cli() -> bool:
    """Check if gh CLI is available and authenticated."""
    try:
        subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def generate_release_notes(version: str, commits: list[str], tag: str | None) -> str:
    """Generate markdown release notes."""
    bullet_commits = (
        "\n".join(f"- {c}" for c in commits) if commits else "- No commits found"
    )

    return f"""# Release {version}

## Highlights
- TODO: add key features/fixes

## Changes (since {tag or 'initial'})
{bullet_commits}

## Upgrade Notes
- TODO: migration notes, breaking changes, dependency updates
"""


def update_pyproject(repo_root: Path, new_version: str) -> None:
    """Update version in pyproject.toml."""
    pyproject = repo_root / "pyproject.toml"
    text = pyproject.read_text()
    new_text = re.sub(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        text,
        flags=re.MULTILINE,
    )
    pyproject.write_text(new_text)


def run_git_commands(
    repo_root: Path, new_version: str, release_notes: str, dry_run: bool
) -> bool:
    """Execute git commands for release. Returns True on success."""
    tag = f"v{new_version}"

    if dry_run:
        print(f"\n[DRY-RUN] Would update pyproject.toml to version {new_version}")
        print(f'[DRY-RUN] Would commit: "Bump version to {new_version}"')
        print(f"[DRY-RUN] Would create tag: {tag}")
        print("[DRY-RUN] Would push to origin with tags")
        print(f"[DRY-RUN] Would create GitHub release {tag}")
        print("\n[DRY-RUN] Release notes preview:")
        print("-" * 40)
        print(release_notes)
        print("-" * 40)
        return True

    # Update pyproject.toml
    update_pyproject(repo_root, new_version)
    print(f"  Updated pyproject.toml to version {new_version}")

    # Git commit
    subprocess.run(
        ["git", "add", "pyproject.toml"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"Bump version to {new_version}"],
        cwd=repo_root,
        check=True,
    )
    print(f'  Created commit: "Bump version to {new_version}"')

    # Create tag
    subprocess.run(
        ["git", "tag", tag],
        cwd=repo_root,
        check=True,
    )
    print(f"  Created tag: {tag}")

    # Push commit and tag separately (--follow-tags can fail on non-tracking branches)
    subprocess.run(
        ["git", "push", "origin", "HEAD"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        ["git", "push", "origin", tag],
        cwd=repo_root,
        check=True,
    )
    print(f"  Pushed to origin with tag {tag}")

    # Create GitHub release with release notes
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(release_notes)
        notes_file = f.name

    try:
        subprocess.run(
            ["gh", "release", "create", tag, "-t", tag, "-F", notes_file],
            cwd=repo_root,
            check=True,
        )
        print(f"  Created GitHub release {tag}")
    finally:
        Path(notes_file).unlink()

    return True


def interactive_mode(repo_root: Path, dry_run: bool, custom_notes: Path | None) -> int:
    """Run interactive version bump flow."""
    current_version = get_current_version(repo_root)
    last_tag = get_last_tag()
    commits = get_commits_since_tag(last_tag)
    current_branch = get_current_branch()

    print(f"\nCurrent version: {current_version}")
    print(f"Current branch: {current_branch}")

    if current_branch != "main":
        print(f"\n  Warning: You are not on 'main' branch!")

    if not is_working_tree_clean():
        print("\n  Error: Working tree is dirty. Commit or stash changes first.")
        return 1

    if not check_gh_cli():
        print("\n  Error: gh CLI not found or not authenticated.")
        print("  Install and authenticate: gh auth login")
        return 1

    # Show commits since last tag
    if commits:
        print(f"\nChanges since {last_tag or 'initial'}:")
        for commit in commits[:10]:  # Show max 10
            print(f"  - {commit}")
        if len(commits) > 10:
            print(f"  ... and {len(commits) - 10} more commits")
    else:
        print(f"\nNo commits since {last_tag or 'initial'}")

    # Calculate versions for display
    patch_version = bump_version(current_version, "patch")
    minor_version = bump_version(current_version, "minor")
    major_version = bump_version(current_version, "major")

    # Ask for bump type
    choices = [
        questionary.Choice(
            title=f"patch  ({current_version} -> {patch_version})",
            value="patch",
        ),
        questionary.Choice(
            title=f"minor  ({current_version} -> {minor_version})",
            value="minor",
        ),
        questionary.Choice(
            title=f"major  ({current_version} -> {major_version})",
            value="major",
        ),
    ]

    bump_type = questionary.select(
        "Select version bump type:",
        choices=choices,
        style=CUSTOM_STYLE,
    ).ask()

    if bump_type is None:
        print("Aborted.")
        return 1

    new_version = bump_version(current_version, bump_type)

    # Generate or load release notes
    if custom_notes:
        release_notes = custom_notes.read_text()
    else:
        release_notes = generate_release_notes(new_version, commits, last_tag)

    # Confirm
    if not dry_run:
        proceed = questionary.confirm(
            f"Proceed with release v{new_version}?",
            default=True,
            style=CUSTOM_STYLE,
        ).ask()

        if not proceed:
            print("Aborted.")
            return 1

    print()
    if run_git_commands(repo_root, new_version, release_notes, dry_run):
        if not dry_run:
            print(f"\n  Release v{new_version} completed!")
        return 0
    return 1


def non_interactive_mode(
    repo_root: Path,
    bump_type: BumpType,
    dry_run: bool,
    skip_confirm: bool,
    custom_notes: Path | None,
) -> int:
    """Run non-interactive version bump."""
    current_version = get_current_version(repo_root)
    last_tag = get_last_tag()
    commits = get_commits_since_tag(last_tag)
    current_branch = get_current_branch()

    print(f"Current version: {current_version}")
    print(f"Current branch: {current_branch}")

    if current_branch != "main":
        print(f"Warning: You are not on 'main' branch!")

    if not is_working_tree_clean():
        print("Error: Working tree is dirty. Commit or stash changes first.")
        return 1

    if not check_gh_cli():
        print("Error: gh CLI not found or not authenticated.")
        return 1

    new_version = bump_version(current_version, bump_type)
    print(f"New version: {new_version}")

    if commits:
        print(f"\nChanges since {last_tag or 'initial'}:")
        for commit in commits[:5]:
            print(f"  - {commit}")
        if len(commits) > 5:
            print(f"  ... and {len(commits) - 5} more commits")

    # Generate or load release notes
    if custom_notes:
        release_notes = custom_notes.read_text()
    else:
        release_notes = generate_release_notes(new_version, commits, last_tag)

    # Confirm unless --yes
    if not dry_run and not skip_confirm:
        response = input(f"\nProceed with release v{new_version}? [Y/n] ")
        if response.lower() not in ("", "y", "yes"):
            print("Aborted.")
            return 1

    print()
    if run_git_commands(repo_root, new_version, release_notes, dry_run):
        if not dry_run:
            print(f"\nRelease v{new_version} completed!")
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Version bump and release automation for linux-benchmark-lib"
    )

    bump_group = parser.add_mutually_exclusive_group()
    bump_group.add_argument(
        "--patch", action="store_true", help="Bump patch version (X.Y.Z -> X.Y.Z+1)"
    )
    bump_group.add_argument(
        "--minor", action="store_true", help="Bump minor version (X.Y.Z -> X.Y+1.0)"
    )
    bump_group.add_argument(
        "--major", action="store_true", help="Bump major version (X.Y.Z -> X+1.0.0)"
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Preview actions without executing"
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )
    parser.add_argument("--notes", type=Path, help="Custom release notes file")

    args = parser.parse_args()

    repo_root = find_repo_root()

    # Validate custom notes file
    if args.notes and not args.notes.exists():
        print(f"Error: Release notes file not found: {args.notes}")
        return 1

    # Determine mode
    if args.patch:
        return non_interactive_mode(
            repo_root, "patch", args.dry_run, args.yes, args.notes
        )
    elif args.minor:
        return non_interactive_mode(
            repo_root, "minor", args.dry_run, args.yes, args.notes
        )
    elif args.major:
        return non_interactive_mode(
            repo_root, "major", args.dry_run, args.yes, args.notes
        )
    else:
        # Interactive mode
        return interactive_mode(repo_root, args.dry_run, args.notes)


if __name__ == "__main__":
    sys.exit(main())
