"""Plugin registry factory and management helpers."""

import logging
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Any, Union

from lb_runner.plugin_system.builtin import builtin_plugins
from lb_runner.plugin_system.registry import PluginRegistry, USER_PLUGIN_DIR
# Alias to preserve compatibility with test monkeypatches expecting a `registry` module
from lb_runner.plugin_system import registry as registry  # noqa: F401

logger = logging.getLogger(__name__)

_REGISTRY_CACHE: PluginRegistry | None = None


def create_registry(refresh: bool = False) -> PluginRegistry:
    """
    Build a plugin registry with built-ins, entry points, and user plugins.
    """
    global _REGISTRY_CACHE
    if not refresh and _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    _REGISTRY_CACHE = PluginRegistry(builtin_plugins())
    return _REGISTRY_CACHE


class PluginInstaller:
    """Helper to install and uninstall user plugins."""

    def __init__(self):
        self.plugin_dir = USER_PLUGIN_DIR
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    def install(self, source_path: Union[Path, str], manifest_path: Optional[Path] = None, force: bool = False) -> str:
        """
        Install a plugin from a file (.py), directory, archive (.zip, .tar.gz), or git URL.
        Returns the name of the installed plugin.
        """
        if isinstance(source_path, Path):
            raw_source = str(source_path)
        else:
            raw_source = source_path

        if self._looks_like_git_url(raw_source):
            return self._install_from_git(raw_source, force)

        source_path = Path(raw_source).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source not found: {source_path}")

        if source_path.is_dir():
            return self._install_directory(source_path, force)

        if source_path.suffix == ".py":
            return self._install_file(source_path, manifest_path, force)

        if self._is_supported_archive(source_path):
            return self._install_archive(source_path, force)

        raise ValueError(
            f"Unsupported source: {source_path}. Expected a .py file, directory, or archive (.zip/.tar.gz)"
        )

    def uninstall(self, plugin_name: str) -> bool:
        """
        Uninstall a user plugin by name. 
        Removes the plugin directory (if valid) or the .py/.yaml files.
        """
        target_py = self.plugin_dir / f"{plugin_name}.py"
        target_yaml = self.plugin_dir / f"{plugin_name}.yaml"
        target_yml = self.plugin_dir / f"{plugin_name}.yml"
        target_dir = self.plugin_dir / plugin_name

        found = False
        
        # 1. Check for directory plugin
        if target_dir.exists() and target_dir.is_dir():
            shutil.rmtree(target_dir)
            logger.info(f"Removed plugin directory: {target_dir}")
            found = True

        # 2. Check for single file plugin
        if target_py.exists():
            target_py.unlink()
            logger.info(f"Removed plugin source: {target_py}")
            found = True
        
        for manifest in [target_yaml, target_yml]:
            if manifest.exists():
                manifest.unlink()
                logger.info(f"Removed plugin manifest: {manifest}")

        if not found:
            logger.warning(f"Plugin '{plugin_name}' not found in user directory.")
            
        return found

    def package(self, source_dir: Path, output_path: Optional[Path] = None) -> Path:
        """
        Create a compressed plugin archive (.tar.gz) from a directory.
        Returns the path to the created archive.
        """
        source_dir = Path(source_dir).resolve()
        if not source_dir.is_dir():
            raise ValueError(f"Source directory not found: {source_dir}")

        target = Path(output_path).resolve() if output_path else Path(tempfile.mkdtemp()) / f"{source_dir.name}.tar.gz"
        return self._package_directory(source_dir, target)

    def _install_file(self, py_path: Path, manifest_path: Optional[Path], force: bool) -> str:
        target_py = self.plugin_dir / py_path.name
        
        if target_py.exists() and not force:
            raise FileExistsError(f"Plugin '{py_path.stem}' already exists. Use --force to overwrite.")

        shutil.copy2(py_path, target_py)
        logger.info(f"Installed plugin source to {target_py}")
        
        if manifest_path:
            manifest_path = Path(manifest_path)
            # Rename manifest to match plugin name for consistency
            target_manifest = self.plugin_dir / f"{py_path.stem}.yaml"
            shutil.copy2(manifest_path, target_manifest)
            logger.info(f"Installed plugin manifest to {target_manifest}")
            
        return py_path.stem

    def _install_archive(self, archive_path: Path, force: bool) -> str:
        """Extract archive and install as a directory plugin."""
        logger.info(f"Extracting archive {archive_path}...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            
            # Extract
            if archive_path.suffix == ".zip":
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(tmp_path)
            else:
                with tarfile.open(archive_path, 'r') as tar_ref:
                    tar_ref.extractall(tmp_path, filter="data")
            
            # Inspect structure
            items = list(tmp_path.iterdir())
            # If archive contains a single top-level folder, use that
            if len(items) == 1 and items[0].is_dir():
                source_dir = items[0]
            else:
                # Archive is flat or mixed; use the extraction root
                # Ideally we rename it to match the archive stem for the final install
                source_dir = tmp_path
                # Check if we can infer a better name from the files?
                # For now, _install_directory will use source_dir.name, which is random for tmp_dir.
                # We should rename/copy it to a folder with the archive name.
                archive_stem = archive_path.name.split('.')[0]
                if source_dir.name != archive_stem:
                    # We are inside a temp dir with random name. 
                    # But _install_directory uses the source_dir.name as the plugin name.
                    # So we must ensure source_dir has the desired plugin name.
                    # However, we can't rename the temp dir easily.
                    # Instead, we pass the desired name to _install_directory if we refactor it,
                    # or we move content to a subdir.
                    structured_dir = tmp_path / archive_stem
                    structured_dir.mkdir()
                    for item in items:
                        shutil.move(str(item), str(structured_dir))
                    source_dir = structured_dir

            return self._install_directory(source_dir, force)

    def _install_directory(self, source_dir: Path, force: bool) -> str:
        """Install a plugin from a directory.

        If the directory contains a single top-level .py file (e.g., dummy.py),
        install it as a flat plugin file named after that stem. Otherwise, copy
        the entire directory under the plugin dir preserving its name.
        """
        source_dir = source_dir.resolve()

        # Validation: Ensure it looks like a plugin (has python files)
        py_files = list(source_dir.glob("*.py"))
        if not py_files and not any(source_dir.rglob("*.py")):
            raise ValueError(f"Directory '{source_dir.name}' does not contain any Python files.")

        if len(py_files) == 1 and (source_dir / "__init__.py").exists():
            # Treat as flat plugin: copy the module to USER_PLUGIN_DIR/<stem>.py
            module = py_files[0]
            plugin_name = module.stem
            target_py = self.plugin_dir / f"{plugin_name}.py"
            if target_py.exists():
                if not force:
                    raise FileExistsError(f"Plugin '{plugin_name}' already exists at {target_py}. Use --force to overwrite.")
                target_py.unlink()
            shutil.copy2(module, target_py)
            logger.info(f"Installed plugin source to {target_py}")
            return plugin_name

        plugin_name = source_dir.name
        target_dir = self.plugin_dir / plugin_name

        if target_dir.exists():
            if not force:
                raise FileExistsError(f"Plugin '{plugin_name}' already exists at {target_dir}. Use --force to overwrite.")
            if target_dir.is_dir():
                shutil.rmtree(target_dir)
            else:
                target_dir.unlink()  # It was a file

        shutil.copytree(source_dir, target_dir)
        logger.info(f"Installed plugin directory to {target_dir}")
        return plugin_name

    def _package_directory(self, source_dir: Path, archive_path: Path) -> Path:
        """Tar/gzip a plugin directory into the given archive path."""
        archive_path = archive_path.resolve()
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive_path, "w:gz") as tar:
            for item in Path(source_dir).iterdir():
                tar.add(item, arcname=item.name)

        logger.info(f"Compressed plugin directory {source_dir} -> {archive_path}")
        return archive_path

    def _is_supported_archive(self, path: Path) -> bool:
        """Return True when the path looks like an installable archive."""
        suffixes = path.suffixes
        combined = "".join(suffixes[-2:]) if len(suffixes) >= 2 else ""
        return path.suffix in {".zip", ".gz", ".tar", ".tgz"} or combined in {".tar.gz", ".tar.bz2", ".tar.xz"}

    # --- Git helpers ---

    def _looks_like_git_url(self, value: str) -> bool:
        """Return True when the provided string resembles a git clone URL."""
        lowered = value.lower()
        if lowered.startswith(("http://", "https://", "ssh://", "git@", "file://")):
            return True
        return lowered.endswith(".git") and ("://" in lowered or lowered.startswith("git@"))

    def _install_from_git(self, url: str, force: bool) -> str:
        """Clone a git repository and install the plugin from the checked-out tree."""
        if shutil.which("git") is None:
            raise RuntimeError("git is required to install plugins from repositories.")

        # Infer plugin name from URL (e.g. "https://.../my-plugin.git" -> "my-plugin")
        plugin_name = url.rstrip("/").split("/")[-1]
        if plugin_name.endswith(".git"):
            plugin_name = plugin_name[:-4]
            
        # Fallback if URL parsing fails strangely
        if not plugin_name:
            plugin_name = "plugin_from_git"

        with tempfile.TemporaryDirectory() as tmp_dir:
            clone_path = Path(tmp_dir) / plugin_name
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", url, str(clone_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                stdout = exc.stdout.strip() if exc.stdout else ""
                stderr = exc.stderr.strip() if exc.stderr else ""
                msg = f"git clone failed for {url}: {stderr or stdout or exc}"
                raise RuntimeError(msg) from exc

            return self.install(clone_path, force=force)
