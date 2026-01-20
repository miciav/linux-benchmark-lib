import json
import logging

import pytest

from lb_common.logs.handlers.jsonl_handler import JsonlLogHandler


pytestmark = pytest.mark.unit_runner


def test_jsonl_handler_writes_file(tmp_path) -> None:
    logger = logging.getLogger("jsonl-handler-test")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    handler = JsonlLogHandler(
        output_dir=tmp_path,
        component="runner",
        host="host1",
        run_id="run-1",
        workload="stress_ng",
        repetition=2,
    )
    logger.addHandler(handler)

    logger.info("hello jsonl")
    handler.flush()
    handler.close()

    log_path = tmp_path / "logs" / "runner-host1.jsonl"
    payload = json.loads(log_path.read_text(encoding="utf-8").strip())

    assert payload["message"] == "hello jsonl"
    assert payload["component"] == "runner"
    assert payload["host"] == "host1"
    assert payload["run_id"] == "run-1"
    assert payload["workload"] == "stress_ng"
    assert payload["repetition"] == 2


def test_jsonl_handler_includes_phase_tag(tmp_path) -> None:
    logger = logging.getLogger("jsonl-handler-phase")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)

    handler = JsonlLogHandler(
        output_dir=tmp_path,
        component="runner",
        host="host1",
        run_id="run-1",
        workload="stress_ng",
        repetition=1,
    )
    logger.addHandler(handler)

    logger.info("hello phase", extra={"lb_phase": "setup"})
    handler.flush()
    handler.close()

    log_path = tmp_path / "logs" / "runner-host1.jsonl"
    payload = json.loads(log_path.read_text(encoding="utf-8").strip())

    assert payload["tags"]["phase"] == "setup"
