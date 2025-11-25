from pathlib import Path

from tools import gen_plugin_assets as gen


def test_render_docker_block_includes_packages():
    block = gen.render_docker_block(["a", "b"], ["c"])
    assert "apt-get install" in block
    assert "a \\" in block
    assert "b \\" in block
    assert "uv pip install -U c" in block


def test_render_ansible_tasks_contains_packages():
    tasks = gen.render_ansible_tasks(["pkg1", "pkg2"], ["pip_pkg"])
    assert "- pkg1" in tasks and "- pkg2" in tasks
    assert "pip_pkg" in tasks


def test_replace_block_swaps_marker_content(tmp_path: Path):
    start = "# START"
    end = "# END"
    path = tmp_path / "file.txt"
    path.write_text("\n".join(["line1", start, "old", end, "line5"]))

    gen.replace_block(path, start, end, "new-line")

    content = path.read_text()
    assert "new-line" in content
    assert "old" not in content
