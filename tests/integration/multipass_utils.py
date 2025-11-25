import os
from services.test_service import TestService


def get_intensity() -> dict:
    """
    Return intensity parameters based on LB_MULTIPASS_FORCE env var.
    Delegates to the shared TestService logic.
    """
    # The service logic includes mapping names like 'stress'/'stress_duration'.
    # The tests expect keys: stress_duration, stress_timeout, dd_count, fio_runtime, fio_size.
    # TestService.get_multipass_intensity returns a superset including these keys.
    return TestService().get_multipass_intensity()