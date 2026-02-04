from tests.helpers.optional_imports import module_available


def test_module_available_detects_existing_module() -> None:
    assert module_available("json") is True


def test_module_available_detects_missing_module() -> None:
    assert module_available("definitely_missing_module_123") is False
