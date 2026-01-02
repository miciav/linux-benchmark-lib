"""Installer utilities for user plugins."""

from __future__ import annotations

import logging
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Union

from lb_plugins.discovery import resolve_user_plugin_dir

logger = logging.getLogger(__name__)


class PluginInstaller:
    """Helper to install and uninstall user plugins."""

    def __init__(self) -> None:
        self.plugin_dir = resolve_user_plugin_dir()
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    def install(
        self,
        source_path: Union[Path, str],
        manifest_path: Optional[Path] = None,
        force: bool = False,
    ) -> str:
        """Install a plugin from file/dir/archive/git URL."""
        raw_source = str(source_path)
        if self._looks_like_git_url(raw_source):
            return self._install_from_git(raw_source, force)

        path = Path(raw_source).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Source not found: {path}")

        if path.is_dir():
            return self._install_directory(path, force)
        if path.suffix == ".py":
            return self._install_file(path, manifest_path, force)
        if self._is_supported_archive(path):
            return self._install_archive(path, force)
        raise ValueError(f"Unsupported source: {path}")

    def package(self, source_dir: Path, archive_path: Path) -> Path:
        """Package a plugin directory into a supported archive format."""
        source_dir = source_dir.resolve()
        if not source_dir.is_dir():
            raise ValueError(f"Source directory not found: {source_dir}")
        archive_path = archive_path.resolve()
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        if archive_path.suffix == ".zip":
            self._package_zip(source_dir, archive_path)
            return archive_path

        mode = self._tar_mode_for(archive_path)
        if mode is None:
            raise ValueError(f"Unsupported archive format: {archive_path}")
        self._package_tar(source_dir, archive_path, mode)
        return archive_path

    def uninstall(self, plugin_name: str) -> bool:
        """Remove plugin artifacts from the user plugin dir."""
        target_py = self.plugin_dir / f"{plugin_name}.py"
        target_yaml = self.plugin_dir / f"{plugin_name}.yaml"
        target_yml = self.plugin_dir / f"{plugin_name}.yml"
        target_dir = self.plugin_dir / plugin_name
        found = False
        if target_dir.exists() and target_dir.is_dir():
            shutil.rmtree(target_dir)
            found = True
        if target_py.exists():
            target_py.unlink()
            found = True
        for manifest in (target_yaml, target_yml):
            if manifest.exists():
                manifest.unlink()
        if not found:
            logger.warning("Plugin '%s' not found in user directory.", plugin_name)
        return found

    def _install_file(
        self, py_path: Path, manifest_path: Optional[Path], force: bool
    ) -> str:
        target_py = self.plugin_dir / py_path.name
        if target_py.exists() and not force:
            raise FileExistsError(
                f"Plugin '{py_path.stem}' already exists. Use --force to overwrite."
            )
        shutil.copy2(py_path, target_py)
        if manifest_path:
            target_manifest = self.plugin_dir / f"{py_path.stem}.yaml"
            shutil.copy2(manifest_path, target_manifest)
        return py_path.stem

    def _install_archive(self, archive_path: Path, force: bool) -> str:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            if archive_path.suffix == ".zip":
                self._safe_extract_zip(archive_path, tmp_path)
            else:
                self._safe_extract_tar(archive_path, tmp_path)
            items = list(tmp_path.iterdir())
            source_dir = items[0] if len(items) == 1 and items[0].is_dir() else tmp_path
            return self._install_directory(source_dir, force)

    def _install_directory(self, source_dir: Path, force: bool) -> str:
        source_dir = source_dir.resolve()
        py_files = list(source_dir.glob("*.py"))
        if not py_files and not any(source_dir.rglob("*.py")):
            raise ValueError(
                f"Directory '{source_dir.name}' does not contain any Python files."
            )

        if self._is_single_module(source_dir, py_files):
            return self._install_module_file(py_files[0], force)

        return self._install_package_dir(source_dir, force)

    @staticmethod
    def _tar_mode_for(archive_path: Path) -> str | None:
        name = archive_path.name
        if name.endswith((".tar.gz", ".tgz")):
            return "w:gz"
        if name.endswith(".tar.bz2"):
            return "w:bz2"
        if name.endswith(".tar.xz"):
            return "w:xz"
        if name.endswith(".tar"):
            return "w"
        if archive_path.suffix in {".gz", ".bz2", ".xz"}:
            return "w:*"
        return None

    @staticmethod
    def _package_zip(source_dir: Path, archive_path: Path) -> None:
        with zipfile.ZipFile(
            archive_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zip_ref:
            for path in source_dir.rglob("*"):
                zip_ref.write(path, path.relative_to(source_dir.parent))

    @staticmethod
    def _package_tar(source_dir: Path, archive_path: Path, mode: str) -> None:
        with tarfile.open(archive_path, mode) as tar_ref:
            tar_ref.add(source_dir, arcname=source_dir.name)

    @staticmethod
    def _is_single_module(source_dir: Path, py_files: list[Path]) -> bool:
        return len(py_files) == 1 and (source_dir / "__init__.py").exists()

    def _install_module_file(self, module: Path, force: bool) -> str:
        plugin_name = module.stem
        target_py = self.plugin_dir / f"{plugin_name}.py"
        self._ensure_target_available(target_py, plugin_name, force)
        if target_py.exists():
            target_py.unlink()
        shutil.copy2(module, target_py)
        return plugin_name

    def _install_package_dir(self, source_dir: Path, force: bool) -> str:
        plugin_name = source_dir.name
        target_dir = self.plugin_dir / plugin_name
        self._ensure_target_available(target_dir, plugin_name, force)
        if target_dir.exists():
            if target_dir.is_dir():
                shutil.rmtree(target_dir)
            else:
                target_dir.unlink()
        shutil.copytree(source_dir, target_dir)
        return plugin_name

    @staticmethod
    def _is_safe_path(base: Path, target: Path) -> bool:
        try:
            target.resolve().relative_to(base.resolve())
            return True
        except ValueError:
            return False

    @classmethod
    def _safe_extract_zip(cls, archive_path: Path, dest: Path) -> None:
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            for member in zip_ref.infolist():
                member_path = dest / member.filename
                if not cls._is_safe_path(dest, member_path):
                    raise ValueError(f"Unsafe path in archive: {member.filename}")
                zip_ref.extract(member, dest)

    @classmethod
    def _safe_extract_tar(cls, archive_path: Path, dest: Path) -> None:
        with tarfile.open(archive_path, "r") as tar_ref:
            for member in tar_ref.getmembers():
                member_path = dest / member.name
                if not cls._is_safe_path(dest, member_path):
                    raise ValueError(f"Unsafe path in archive: {member.name}")
                tar_ref.extract(member, dest, filter="data")

    @staticmethod
    def _ensure_target_available(target: Path, plugin_name: str, force: bool) -> None:
        if target.exists() and not force:
            raise FileExistsError(
                f"Plugin '{plugin_name}' already exists at {target}. "
                "Use --force to overwrite."
            )

    @staticmethod
    def _looks_like_git_url(raw: str) -> bool:
        return raw.startswith(("git@", "http://", "https://", "file://"))

    @staticmethod
    def _is_supported_archive(path: Path) -> bool:
        return path.suffix in {".zip", ".gz", ".tgz", ".bz2", ".xz"}

    def _install_from_git(self, url: str, force: bool) -> str:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_name = self._infer_repo_name(url)
            tmp_path = Path(tmp_dir) / repo_name
            cmd = ["git", "clone", url, str(tmp_path)]
            if force:
                cmd.insert(2, "--depth=1")
            subprocess.run(cmd, check=True, capture_output=True)
            return self._install_directory(tmp_path, force)

    @staticmethod
    def _infer_repo_name(url: str) -> str:
        raw = url.rstrip("/")
        if raw.endswith(".git"):
            raw = raw[: -len(".git")]
        if "://" in raw:
            raw = raw.split("://", 1)[1]
        if ":" in raw and "/" not in raw.split(":", 1)[0]:
            raw = raw.split(":", 1)[1]
        name = raw.rsplit("/", 1)[-1]
        return name or "plugin"
