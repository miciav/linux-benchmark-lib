from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


IO_IMPORT_HINTS = {
    "requests", "httpx",
    "sqlalchemy", "psycopg", "pymongo", "redis",
    "boto3", "google", "azure",
    "subprocess", "socket", "paramiko",
    "fastapi", "flask", "django",
    "typer", "click",
    "pathlib", "os",
}

MANAGER_NAME_RE = re.compile(r"(manager|service|controller|orchestrator|handler|pipeline)", re.I)


@dataclass(frozen=True)
class ClassInfo:
    file: str
    name: str
    methods: tuple[str, ...]
    n_methods: int
    n_attrs: int
    n_imports: int
    init_params: int
    suspicious: tuple[str, ...]


_SKIP_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "build",
    "dist",
    "site",
    "arch_report",
    "_user",
}


def _should_skip(path: Path) -> bool:
    return any(part in _SKIP_DIRS for part in path.parts)


def py_files_under(pkg: Path) -> list[Path]:
    return [
        p
        for p in pkg.rglob("*.py")
        if p.is_file() and not _should_skip(p)
    ]


def top_level_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    if not isinstance(tree, ast.Module):
        return imports

    for node in tree.body:
        if isinstance(node, ast.Import):
            for n in node.names:
                imports.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


def _count_init_params(fn: ast.FunctionDef) -> int:
    return max(0, len(fn.args.args) - 1)  # exclude self


def class_infos(path: Path) -> list[ClassInfo]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imports = top_level_imports(tree)

    infos: list[ClassInfo] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        methods: list[str] = []
        attrs = 0
        init_params = 0
        suspicious: list[str] = []

        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                methods.append(item.name)
                if item.name == "__init__":
                    init_params = _count_init_params(item)
            elif isinstance(item, (ast.AnnAssign, ast.Assign)):
                attrs += 1

        uniq_methods = tuple(sorted(set(methods)))

        # Heuristics: surface candidates (not “proof”, but good leads).
        if MANAGER_NAME_RE.search(node.name):
            suspicious.append("name_suggests_orchestrator")
        if len(uniq_methods) >= 15:
            suspicious.append("many_methods")
        if init_params >= 8:
            suspicious.append("init_too_many_params")
        if len(imports.intersection(IO_IMPORT_HINTS)) >= 2 and len(uniq_methods) >= 6:
            suspicious.append("io_plus_logic_mixed")
        if len(imports) >= 25:
            suspicious.append("module_many_imports")

        infos.append(
            ClassInfo(
                file=str(path),
                name=node.name,
                methods=uniq_methods,
                n_methods=len(uniq_methods),
                n_attrs=attrs,
                n_imports=len(imports),
                init_params=init_params,
                suspicious=tuple(suspicious),
            )
        )

    return infos


def similarity(methods_a: tuple[str, ...], methods_b: tuple[str, ...]) -> float:
    sa, sb = set(methods_a), set(methods_b)
    if not sa and not sb:
        return 0.0
    jaccard = len(sa & sb) / max(1, len(sa | sb))
    seq = SequenceMatcher(None, " ".join(sorted(sa)), " ".join(sorted(sb))).ratio()
    return 0.5 * jaccard + 0.5 * seq


def main(pkg_dir: str) -> None:
    pkg = Path(pkg_dir)
    if not pkg.exists():
        raise SystemExit(f"Package directory not found: {pkg_dir}")

    all_infos: list[ClassInfo] = []
    for f in py_files_under(pkg):
        try:
            all_infos.extend(class_infos(f))
        except SyntaxError as e:
            # Keep going; repos may have broken files.
            print(f"[WARN] SyntaxError in {f}: {e}")

    out_dir = Path("arch_report")
    out_dir.mkdir(exist_ok=True)

    hotspots = [ci for ci in all_infos if ci.suspicious]
    hotspots.sort(key=lambda x: (len(x.suspicious), x.n_methods, x.init_params, x.n_imports), reverse=True)

    (out_dir / "hotspots.txt").write_text(
        "\n".join(
            f"{h.file}:{h.name} | methods={h.n_methods} init_params={h.init_params} imports={h.n_imports} flags={list(h.suspicious)}"
            for h in hotspots[:500]
        ) + "\n",
        encoding="utf-8",
    )

    pairs: list[tuple[float, ClassInfo, ClassInfo]] = []
    for i in range(len(all_infos)):
        for j in range(i + 1, len(all_infos)):
            a, b = all_infos[i], all_infos[j]
            if a.name == b.name:
                continue
            sim = similarity(a.methods, b.methods)
            if sim >= 0.72 and min(a.n_methods, b.n_methods) >= 5:
                pairs.append((sim, a, b))
    pairs.sort(key=lambda x: x[0], reverse=True)

    (out_dir / "duplication_candidates.txt").write_text(
        "\n".join(
            (
                f"sim={sim:.2f} | {a.file}:{a.name}  <->  {b.file}:{b.name}\n"
                f"  common_methods={sorted(set(a.methods) & set(b.methods))[:30]}\n"
            )
            for sim, a, b in pairs[:500]
        ) + "\n",
        encoding="utf-8",
    )

    print("Wrote:")
    print(" - arch_report/hotspots.txt")
    print(" - arch_report/duplication_candidates.txt")
    print(f"Classes analyzed: {len(all_infos)} | hotspots: {len(hotspots)} | dup_pairs: {len(pairs)}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/arch_smells.py <package_dir>")
        raise SystemExit(2)

    main(sys.argv[1])
