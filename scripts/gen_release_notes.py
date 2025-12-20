"""
Generate a Markdown skeleton for release notes based on recent commits.

Usage:
    uv run python scripts/gen_release_notes.py --version 0.21.0 --output release_notes_0.21.0.md
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from textwrap import dedent

from lb_common import configure_logging

def git_log(from_ref: str | None = None, to_ref: str = "HEAD") -> list[str]:
    """Return a list of commit subjects between refs."""
    range_spec = f"{from_ref}..{to_ref}" if from_ref else to_ref
    result = subprocess.run(
        ["git", "log", "--oneline", "--no-merges", range_spec],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Generate release notes skeleton.")
    parser.add_argument("--version", required=True, help="Version string (e.g., 0.21.0)")
    parser.add_argument("--output", required=True, help="Output markdown file")
    parser.add_argument("--from-ref", help="Optional git ref to start from (exclusive)")
    args = parser.parse_args()

    commits = git_log(args.from_ref)
    bullet_commits = "\n".join(f"- {c}" for c in commits)

    content = dedent(
        f"""\
        # Release {args.version}

        ## Highlights
        - TODO: add key features/fixes

        ## Changes (since {args.from_ref or 'initial'})
        {bullet_commits or '- No commits found'}

        ## Upgrade Notes
        - TODO: migration notes, breaking changes, dependency updates

        """
    )

    Path(args.output).write_text(content, encoding="utf-8")
    print(f"Wrote release notes to {args.output}")


if __name__ == "__main__":
    main()
