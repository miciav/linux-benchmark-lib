"""Tests for the FIO plugin parsing helpers."""

import pytest

from lb_runner.plugins.fio.plugin import FIOConfig, FIOGenerator

pytestmark = [pytest.mark.runner, pytest.mark.plugins]



def _make_generator() -> FIOGenerator:
    return FIOGenerator(FIOConfig())


def test_parse_json_output_with_prefixed_noise():
    """Ensure fio JSON is parsed even when warnings precede the payload."""
    generator = _make_generator()
    noisy_output = """
note: both iodepth >= 1 and synchronous I/O engine are selected, queue depth will be capped at 1
fio: terminating on signal 15
{
  "jobs": [
    {
      "read": {
        "iops": 1234.5,
        "bw": 2048,
        "lat_ns": {"mean": 2000000}
      },
      "write": {
        "iops": 2345.6,
        "bw": 4096,
        "lat_ns": {"mean": 6000000}
      }
    }
  ]
}
trailing text that should be ignored
""".strip()

    parsed = generator._parse_json_output(noisy_output)  # pylint: disable=protected-access

    assert parsed["read_iops"] == pytest.approx(1234.5)
    assert parsed["write_iops"] == pytest.approx(2345.6)
    assert parsed["read_bw_mb"] == pytest.approx(2.0)
    assert parsed["write_bw_mb"] == pytest.approx(4.0)
    assert parsed["read_lat_ms"] == pytest.approx(2.0)
    assert parsed["write_lat_ms"] == pytest.approx(6.0)


def test_parse_json_output_without_payload(caplog):
    """Return an empty dict and log an error when no JSON is present."""
    generator = _make_generator()

    with caplog.at_level("ERROR"):
        parsed = generator._parse_json_output("fio: nothing to see here")  # pylint: disable=protected-access

    assert parsed == {}
    assert "Failed to locate fio JSON payload" in caplog.text
