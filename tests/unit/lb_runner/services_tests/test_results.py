"""Unit tests for result merging and persistence."""

from pathlib import Path

import pytest

from lb_runner.services.results import merge_results


pytestmark = [pytest.mark.unit, pytest.mark.unit_runner]


class TestMergeResults:
    """Tests for merge_results function."""

    def test_merge_results_overwrites_repetition(self, tmp_path: Path) -> None:
        """New result for same repetition overwrites old."""
        results_file = tmp_path / "out.json"
        results_file.write_text(
            '[{"repetition": 1, "value": "old"}, {"repetition": 2, "value": "keep"}]'
        )
        merged = merge_results(results_file, [{"repetition": 1, "value": "new"}])
        assert any(r["value"] == "new" for r in merged)
        assert any(r["value"] == "keep" for r in merged)

    def test_merge_results_adds_new_repetition(self, tmp_path: Path) -> None:
        """New repetition is appended."""
        results_file = tmp_path / "out.json"
        results_file.write_text('[{"repetition": 1, "value": "first"}]')
        merged = merge_results(results_file, [{"repetition": 2, "value": "second"}])
        assert len(merged) == 2
        assert any(r["repetition"] == 1 for r in merged)
        assert any(r["repetition"] == 2 for r in merged)

    def test_merge_results_creates_from_empty(self, tmp_path: Path) -> None:
        """Merging into non-existent file creates new list."""
        results_file = tmp_path / "new.json"
        merged = merge_results(results_file, [{"repetition": 1, "value": "new"}])
        assert merged == [{"repetition": 1, "value": "new"}]
