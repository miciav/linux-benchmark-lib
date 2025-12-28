#!/usr/bin/env bash
set -euo pipefail

# Professional architecture audit runner
# Usage:
#   ./scripts/arch_audit.sh <target_package_or_dir>
#
# Example:
#   ./scripts/arch_audit.sh lb_controller

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "Usage: $0 <target_package_or_dir>"
  exit 1
fi

# Repo root (parent of this script)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/arch_report"

mkdir -p "$OUT"

# Guardrails
if [[ -z "${OUT:-}" || "$OUT" == "/" ]]; then
  echo "Refusing to write report: OUT is invalid: '$OUT'"
  exit 1
fi

log() { echo -e "$*"; }

run_step() {
  local title="$1"
  shift
  log "\n[$title]"
  # We want a report even if some tools fail:
  set +e
  "$@"
  local rc=$?
  set -e
  return $rc
}

# Export for heredoc python blocks (so we can use <<'PY' safely)
export AUDIT_ROOT="$ROOT"
export AUDIT_OUT="$OUT"
export AUDIT_TARGET="$TARGET"

run_step "1/12 System + Python info" bash -lc "
  uv run python -V > \"$OUT/python_version.txt\" 2>&1 || true
  uv run python -c \"import platform; print(platform.platform())\" > \"$OUT/platform.txt\" 2>&1 || true
  echo \"ROOT=$ROOT\" > \"$OUT/paths.txt\"
  echo \"OUT=$OUT\" >> \"$OUT/paths.txt\"
  echo \"TARGET=$TARGET\" >> \"$OUT/paths.txt\"
"

run_step "2/12 Tree snapshot" bash -lc "
  cd \"$ROOT\" || exit 1
  find . -maxdepth 4 -type d | sed 's|^\\./||' | sort > \"$OUT/tree_dirs.txt\"
  find . -maxdepth 4 -type f \\( -name '*.py' -o -name 'pyproject.toml' -o -name '*.md' \\) | sed 's|^\\./||' | sort > \"$OUT/tree_files.txt\"
"

run_step "3/12 Ruff (lint)" bash -lc "
  cd \"$ROOT\" || exit 1
  uv run ruff check . --output-format=concise > \"$OUT/ruff_check.txt\" 2>&1 || true
"

run_step "4/12 Ruff (stats)" bash -lc "
  cd \"$ROOT\" || exit 1
  uv run ruff check . --statistics > \"$OUT/ruff_stats.txt\" 2>&1 || true
"

run_step "5/12 Type checking" bash -lc "
  cd \"$ROOT\" || exit 1
  if uv run python -c \"import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('pyright') else 1)\"; then
    uv run pyright > \"$OUT/pyright.txt\" 2>&1 || true
  else
    uv run mypy . > \"$OUT/mypy.txt\" 2>&1 || true
  fi
"

run_step "6/12 Complexity (radon/xenon/lizard)" bash -lc "
  cd \"$ROOT\" || exit 1
  uv run radon cc -s -a \"$TARGET\" > \"$OUT/radon_cc.txt\" 2>&1 || true
  uv run radon mi -s \"$TARGET\" > \"$OUT/radon_mi.txt\" 2>&1 || true
  uv run xenon --max-absolute B --max-modules B --max-average A \"$TARGET\" > \"$OUT/xenon.txt\" 2>&1 || true
  uv run lizard -l python -C 10 -L 200 \"$TARGET\" > \"$OUT/lizard.txt\" 2>&1 || true
"

run_step "7/12 Dead code (vulture)" bash -lc "
  cd \"$ROOT\" || exit 1
  uv run vulture \"$TARGET\" --min-confidence 80 > \"$OUT/vulture.txt\" 2>&1 || true
"

run_step "8/12 Dependency hygiene (deptry)" bash -lc "
  cd \"$ROOT\" || exit 1
  uv run deptry . > \"$OUT/deptry.txt\" 2>&1 || true
"

run_step "9/12 Security (pip-audit/bandit/semgrep)" bash -lc "
  cd \"$ROOT\" || exit 1
  uv run pip-audit > \"$OUT/pip_audit.txt\" 2>&1 || true
  uv run bandit -r \"$TARGET\" -q > \"$OUT/bandit.txt\" 2>&1 || true
  uv run semgrep --config auto \"$TARGET\" > \"$OUT/semgrep_auto.txt\" 2>&1 || true
"

# --- Grimp: robust block (no tee, no fragile pipes) ---
run_step "10/12 Import graph + cycles (grimp)" bash -lc "
  cd \"$ROOT\" || exit 1
  uv run python - <<'PY' > \"$OUT/grimp_cycles.txt\" 2>&1 || true
import os
import sys

target = os.environ.get('AUDIT_TARGET', '')
root = os.environ.get('AUDIT_ROOT', '.')

try:
    import grimp
except Exception as e:
    print('grimp import failed:', e)
    sys.exit(0)

# Try multiple ways to get Project depending on grimp version
Project = getattr(grimp, 'Project', None)
if Project is None:
    try:
        from grimp.adaptors.project import Project  # type: ignore
    except Exception as e:
        print('Could not locate Project in grimp.')
        print('Installed grimp version:', getattr(grimp, '__version__', 'unknown'))
        print('Error:', e)
        sys.exit(0)

try:
    p = Project(root)
    cycles = p.find_import_cycles(target)
    print(f'Import cycles in {target}: {len(cycles)}')
    for c in cycles[:200]:
        print('  - ' + ' -> '.join(c))
except Exception as e:
    print('Error while computing cycles:', e)
PY
"

# pydeps is optional; graphviz is required to render
run_step "11/12 Import diagram (pydeps)" bash -lc "
  cd \"$ROOT\" || exit 1
  if command -v dot >/dev/null 2>&1; then
    uv run pydeps \"$TARGET\" --max-bacon=2 --noshow --show-deps -o \"$OUT/pydeps.svg\" > \"$OUT/pydeps.txt\" 2>&1 || true
  else
    echo \"Graphviz not found (dot). Install with: brew install graphviz\" > \"$OUT/pydeps.txt\"
  fi
"

run_step "12/12 Tests + coverage (if tests exist)" bash -lc "
  cd \"$ROOT\" || exit 1
  if [[ -d \"$ROOT/tests\" ]]; then
    uv run pytest -q --disable-warnings --maxfail=1 --cov=\"$TARGET\" --cov-report=term-missing > \"$OUT/pytest_cov.txt\" 2>&1 || true
  else
    echo \"No ./tests directory found\" > \"$OUT/pytest_cov.txt\"
  fi
"

log "\nDone. Report folder: $OUT"
