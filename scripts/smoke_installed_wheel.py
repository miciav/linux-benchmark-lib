r"""Smoke-test an installed linux-benchmark-lib wheel.

Run it with the interpreter of a venv holding the built wheel, from outside the
checkout, so that the installed copy is what gets imported:

    cd /tmp && /path/to/venv/bin/python -I \
        /path/to/checkout/scripts/smoke_installed_wheel.py --source /path/to/checkout

The unit tests run against the source tree, where every asset is present. The
wheel is assembled from the package-data globs in pyproject.toml, and an asset
the globs miss (a playbook, the PTS .deb, a manifest) only shows up after an
install. That is the gap this script closes.
"""

from __future__ import annotations

import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGES = (
    "lb_common",
    "lb_plugins",
    "lb_runner",
    "lb_controller",
    "lb_app",
    "lb_analytics",
    "lb_ui",
    "lb_provisioner",
)
# Mirrors [tool.setuptools.package-data] in pyproject.toml (lb_gui needs the
# gui extra, which the smoke install leaves out).
PACKAGE_DATA = {
    "lb_plugins": "plugins",
    "lb_controller": "ansible",
    "lb_provisioner": "assets",
}
EXPECTED_PLUGINS = 17
PLAYBOOK_ATTRIBUTES = (
    "SETUP_PLAYBOOK",
    "TEARDOWN_PLAYBOOK",
    "COLLECT_PRE_PLAYBOOK",
    "COLLECT_POST_PLAYBOOK",
    "_ansible_setup_path",
    "_ansible_teardown_path",
)


def check_imports_come_from_the_install(source: Path) -> list[str]:
    problems = []
    for name in PACKAGES:
        module = importlib.import_module(name)
        location = Path(module.__file__ or "").resolve()
        if source.resolve() in location.parents:
            problems.append(f"{name} imported from the checkout: {location}")
    return problems


def check_package_data(source: Path) -> list[str]:
    """Every tracked file under a package-data root must be installed."""
    problems = []
    for package, root in PACKAGE_DATA.items():
        installed = Path(importlib.import_module(package).__file__ or "").parent
        tracked = subprocess.run(
            ["git", "-C", str(source), "ls-files", f"{package}/{root}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        for relative in tracked:
            if relative.endswith(".py"):
                continue  # Modules ship as packages, not package data.
            if Path(relative).name.startswith("."):
                continue  # VCS metadata such as .gitignore is not an asset.
            target = installed.parent / relative
            if not target.is_file():
                problems.append(f"missing from the wheel: {relative}")
    return problems


def check_plugins() -> list[str]:
    from lb_plugins.api import create_registry

    plugins = create_registry().available()
    problems = []
    if len(plugins) != EXPECTED_PLUGINS:
        problems.append(
            f"registry loaded {len(plugins)} plugins, expected {EXPECTED_PLUGINS}: "
            f"{sorted(plugins)}"
        )
    for name, plugin in sorted(plugins.items()):
        # get_ansible_*_path() returns None for a missing file, so read the
        # declarations themselves.
        for attribute in PLAYBOOK_ATTRIBUTES:
            declared = getattr(plugin, attribute, None)
            if declared is not None and not Path(declared).is_file():
                problems.append(f"{name}.{attribute} points to a missing {declared}")
    return problems


def check_cli() -> list[str]:
    executable = shutil.which("lb", path=str(Path(sys.executable).parent))
    if executable is None:
        return ["the lb console script is not installed"]
    result = subprocess.run(
        [executable, "--help"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return [f"lb --help exited {result.returncode}: {result.stderr.strip()}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    source = parser.parse_args().source
    problems: list[str] = []
    for check in (
        lambda: check_imports_come_from_the_install(source),
        lambda: check_package_data(source),
        check_plugins,
        check_cli,
    ):
        try:
            problems += check()
        except Exception as exc:  # a broken install must be reported, not crash
            problems.append(f"{type(exc).__name__}: {exc}")
    for problem in problems:
        print(f"FAIL {problem}")
    if not problems:
        print("installed wheel OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
