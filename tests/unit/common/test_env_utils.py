"""Tests for lb_common.env_utils parsing utilities."""

import pytest

from lb_common.env_utils import (
    parse_bool_env,
    parse_float_env,
    parse_int_env,
    parse_labels_env,
)


pytestmark = pytest.mark.unit_runner


class TestParseBoolEnv:
    """Tests for parse_bool_env function."""

    def test_returns_none_for_none(self) -> None:
        assert parse_bool_env(None) is None

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON"])
    def test_returns_true_for_truthy_values(self, value: str) -> None:
        assert parse_bool_env(value) is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", "random", ""])
    def test_returns_false_for_falsy_values(self, value: str) -> None:
        assert parse_bool_env(value) is False

    def test_strips_whitespace(self) -> None:
        assert parse_bool_env("  true  ") is True
        assert parse_bool_env("  1  ") is True


class TestParseIntEnv:
    """Tests for parse_int_env function."""

    def test_returns_none_for_none(self) -> None:
        assert parse_int_env(None) is None

    def test_parses_valid_int(self) -> None:
        assert parse_int_env("42") == 42
        assert parse_int_env("-10") == -10
        assert parse_int_env("0") == 0

    def test_returns_none_for_invalid_int(self) -> None:
        assert parse_int_env("not-a-number") is None
        assert parse_int_env("3.14") is None
        assert parse_int_env("") is None

    def test_handles_whitespace_in_value(self) -> None:
        # int() handles leading/trailing whitespace
        assert parse_int_env("  42  ") == 42


class TestParseFloatEnv:
    """Tests for parse_float_env function."""

    def test_returns_none_for_none(self) -> None:
        assert parse_float_env(None) is None

    def test_parses_valid_float(self) -> None:
        assert parse_float_env("3.14") == 3.14
        assert parse_float_env("-2.5") == -2.5
        assert parse_float_env("0.0") == 0.0
        assert parse_float_env("42") == 42.0

    def test_returns_none_for_invalid_float(self) -> None:
        assert parse_float_env("not-a-number") is None
        assert parse_float_env("") is None

    def test_handles_scientific_notation(self) -> None:
        assert parse_float_env("1e-3") == 0.001
        assert parse_float_env("2.5E2") == 250.0


class TestParseLabelsEnv:
    """Tests for parse_labels_env function."""

    def test_returns_empty_dict_for_none(self) -> None:
        assert parse_labels_env(None) == {}

    def test_returns_empty_dict_for_empty_string(self) -> None:
        assert parse_labels_env("") == {}

    def test_parses_single_label(self) -> None:
        assert parse_labels_env("env=prod") == {"env": "prod"}

    def test_parses_multiple_labels(self) -> None:
        result = parse_labels_env("env=prod,region=us-east,tier=1")
        assert result == {"env": "prod", "region": "us-east", "tier": "1"}

    def test_strips_whitespace(self) -> None:
        result = parse_labels_env("  env = prod , region = us-east  ")
        assert result == {"env": "prod", "region": "us-east"}

    def test_skips_empty_tokens(self) -> None:
        result = parse_labels_env("env=prod,,region=us-east")
        assert result == {"env": "prod", "region": "us-east"}

    def test_skips_tokens_without_equals(self) -> None:
        result = parse_labels_env("env=prod,invalid,region=us-east")
        assert result == {"env": "prod", "region": "us-east"}

    def test_skips_empty_keys(self) -> None:
        result = parse_labels_env("=value,env=prod")
        assert result == {"env": "prod"}

    def test_handles_equals_in_value(self) -> None:
        result = parse_labels_env("query=a=b")
        assert result == {"query": "a=b"}

    def test_allows_empty_values(self) -> None:
        result = parse_labels_env("empty=,env=prod")
        assert result == {"empty": "", "env": "prod"}
