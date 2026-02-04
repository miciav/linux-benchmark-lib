import importlib.util


def module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None
