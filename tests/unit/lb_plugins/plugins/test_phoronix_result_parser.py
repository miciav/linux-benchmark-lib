from __future__ import annotations

import pytest

from lb_plugins.plugins.phoronix_test_suite.plugin import PtsResultParser

pytestmark = [pytest.mark.unit_plugins]


def test_pts_result_parser_normalizes_failure_marker() -> None:
    parser = PtsResultParser("pts-profile")

    rc = parser.normalize_returncode(
        0,
        "the batch mode must first be configured",
    )

    assert rc == 2


def test_pts_result_parser_builds_success_result() -> None:
    parser = PtsResultParser("pts-profile")

    result = parser.build_success_result(
        ["pts", "run"],
        0,
        "ok",
        "/tmp/pts-results",
        "result-id",
        0.0,
    )

    assert result["profile"] == "pts-profile"
    assert result["returncode"] == 0


def test_pts_home_root_resolves_on_the_executing_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from lb_plugins.api import create_registry

    plugin = create_registry().get("pts_ramspeed")
    # The controller must ship "~" unexpanded; the remote host resolves it.
    assert plugin.get_ansible_setup_extravars()["pts_home_root"].startswith("~/")

    monkeypatch.setenv("HOME", str(tmp_path))
    gen = plugin.create_generator(plugin.config_cls())
    env, user_path = gen._prepare_env()
    # PTS concatenates this with file names, so the separator must survive.
    assert env["PTS_USER_PATH_OVERRIDE"] == f"{tmp_path}/.lb/.phoronix-test-suite/"
    assert user_path.is_dir()


def test_pts_export_turns_composite_xml_into_rows(tmp_path) -> None:
    import pandas as pd

    from lb_plugins.api import create_registry

    # <Result> block of a real ramspeed run captured from a Multipass VM.
    composite = """<?xml version="1.0"?>
<PhoronixTestSuite>
  <Result>
    <Identifier>pts/ramspeed-1.4.3</Identifier>
    <Title>RAMspeed SMP</Title>
    <AppVersion>3.5.0</AppVersion>
    <Arguments>COPY -b 3</Arguments>
    <Description>Type: Copy - Benchmark: Integer</Description>
    <Scale>MB/s</Scale>
    <Proportion>HIB</Proportion>
    <Data>
      <Entry>
        <Identifier>1 x 8 GB RAM QEMU</Identifier>
        <Value>76078.07</Value>
        <RawString>90984.5:55966.09:55517.48</RawString>
      </Entry>
    </Data>
  </Result>
</PhoronixTestSuite>
"""
    remote_dir = tmp_path / "remote" / "2026-10-08-2113"
    remote_dir.mkdir(parents=True)
    (remote_dir / "composite.xml").write_text(composite)
    results = [
        {
            "repetition": 1,
            "success": True,
            "generator_result": {"pts_result_dir": str(remote_dir), "returncode": 0},
        }
    ]
    plugin = create_registry().get("pts_ramspeed")
    out = tmp_path / "pts_ramspeed"
    paths = plugin.export_results_to_csv(results, out, "run-1", "pts_ramspeed")

    values = pd.read_csv(out / "pts_ramspeed_pts_results.csv")
    assert out / "pts_ramspeed_pts_results.csv" in paths
    assert values.loc[0, "value"] == 76078.07
    assert values.loc[0, "scale"] == "MB/s"
    assert values.loc[0, "description"] == "Type: Copy - Benchmark: Integer"
    assert values.loc[0, "samples"] == 3

    # On the controller only the collected copy exists; re-export must match.
    for path in remote_dir.iterdir():
        path.unlink()
    regen = plugin.export_results_to_csv(results, out, "run-1", "pts_ramspeed")
    assert pd.read_csv(regen[1]).equals(values)
