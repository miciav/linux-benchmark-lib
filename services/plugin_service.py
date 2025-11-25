"""Plugin registry factory and management helpers."""

import logging
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Any

from plugins.builtin import builtin_plugins
from plugins.registry import PluginRegistry, USER_PLUGIN_DIR

logger = logging.getLogger(__name__)

def create_registry() -> PluginRegistry:
    """
    Build a plugin registry with built-ins, entry points, and user plugins.
    """
    return PluginRegistry(builtin_plugins())


class PluginInstaller:
    """Helper to install and uninstall user plugins."""

    def __init__(self):
        self.plugin_dir = USER_PLUGIN_DIR
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    def install(self, source_path: Path, manifest_path: Optional[Path] = None, force: bool = False) -> str:
        """
        Install a plugin from a file (.py), directory, or archive (.zip, .tar.gz).
        Returns the name of the installed plugin.
        """
        source_path = Path(source_path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source not found: {source_path}")

        if source_path.is_dir():
            # Package the directory into a temporary tarball before installing
            with tempfile.TemporaryDirectory() as tmp_dir:
                archive_path = Path(tmp_dir) / f"{source_path.name}.tar.gz"
                self._package_directory(source_path, archive_path)
                return self._install_archive(archive_path, force)

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
        Removes both the .py file and associated .yaml manifest if present.
        """
        target_py = self.plugin_dir / f"{plugin_name}.py"
        target_yaml = self.plugin_dir / f"{plugin_name}.yaml"
        target_yml = self.plugin_dir / f"{plugin_name}.yml"

        found = False
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
        """Extract archive, look for valid plugin file and manifest, and install."""
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
            
            # Find candidates
            py_files = list(tmp_path.rglob("*.py"))
            py_files = [
                f for f in py_files
                if f.name != "__init__.py" and not f.name.startswith(("test_", "._"))
            ]
            
            if not py_files:
                raise ValueError("No valid Python plugin file found in archive.")
            
            # Heuristic: prefer file with same name as archive stem
            # e.g. sysbench.zip -> sysbench.py
            archive_stem = archive_path.name.split('.')[0]
            main_py = next((f for f in py_files if f.stem == archive_stem), None)
            if not main_py:
                main_py = py_files[0] # Fallback to first found
            
            logger.info(f"Identified main plugin file: {main_py.name}")

            # Find matching manifest
            manifest_files = list(tmp_path.rglob("*.yaml")) + list(tmp_path.rglob("*.yml"))
            main_manifest = None
            if manifest_files:
                 # Prefer sibling of main_py or same name
                 main_manifest = next((f for f in manifest_files if f.stem == main_py.stem), None)
                 if not main_manifest:
                     main_manifest = manifest_files[0]
                 logger.info(f"Identified manifest file: {main_manifest.name}")

            # Install
            return self._install_file(main_py, main_manifest, force)

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


def regenerate_plugin_assets(ui: Optional[Any] = None) -> None:
    """Rebuild Dockerfile/Ansible plugin dependency sections."""
    try:
        from tools import gen_plugin_assets

        gen_plugin_assets.generate()
        if ui:
            ui.show_info("Regenerated plugin assets (Dockerfile, Ansible tasks).")
    except Exception as exc:  # pragma: no cover - best-effort helper
        msg = f"Failed to regenerate plugin assets: {exc}"
        if ui:
            ui.show_warning(msg)
        else:
            logger.warning(msg)
