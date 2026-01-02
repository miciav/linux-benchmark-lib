"""Async LocalRunner entrypoint for Ansible-driven runs."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from lb_plugins.api import create_registry
from lb_runner.api import BenchmarkConfig, LocalRunner, StopToken


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required env var: {name}")
    return value


def _configure_logging_level() -> None:
    """Configure root logger level for event logging.

    When LB_ENABLE_EVENT_LOGGING=1, ensure the root logger accepts INFO-level
    messages so that LBEventLogHandler can receive and emit them.
    The level can be overridden via LB_LOG_LEVEL env var.
    """
    if os.environ.get("LB_ENABLE_EVENT_LOGGING") != "1":
        return
    level_name = os.environ.get("LB_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    # Only lower the level if it's currently higher (more restrictive)
    if root_logger.level == logging.NOTSET or root_logger.level > level:
        root_logger.setLevel(level)


def _configure_stream(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    stdout = sys.stdout

    class _Tee:
        def write(self, data: str) -> int:
            log_file.write(data)
            log_file.flush()
            stdout.write(data)
            stdout.flush()
            return len(data)

        def flush(self) -> None:
            log_file.flush()
            stdout.flush()

    sys.stdout = _Tee()
    sys.stderr = sys.stdout


def _write_status(path: Path | None, rc: int) -> None:
    if path is None:
        return
    payload = {
        "rc": rc,
        "timestamp": time.time(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _maybe_daemonize(env: dict[str, str]) -> int | None:
    if env.get("LB_RUN_DAEMONIZE") != "1":
        return None
    pid_path = Path(_env("LB_RUN_PID_PATH"))
    child_env = env.copy()
    child_env.pop("LB_RUN_DAEMONIZE", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "lb_runner.services.async_localrunner"],
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(proc.pid))
    os._exit(0)


def main() -> int:
    try:
        workload = _env("LB_RUN_WORKLOAD")
        repetition = int(_env("LB_RUN_REPETITION"))
        total_reps = int(_env("LB_RUN_TOTAL_REPS"))
        run_id = os.environ.get("LB_RUN_ID", "")
        host = os.environ.get("LB_RUN_HOST", "")
        config_path = Path(
            os.environ.get("LB_BENCH_CONFIG_PATH", "benchmark_config.generated.json")
        )
        stop_path = Path(os.environ.get("LB_RUN_STOP_FILE", "STOP"))
        log_path = Path(_env("LB_EVENT_STREAM_PATH"))
        status_path_raw = os.environ.get("LB_RUN_STATUS_PATH")
        status_path = Path(status_path_raw) if status_path_raw else None
    except Exception as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    daemon_rc = _maybe_daemonize(os.environ)
    if daemon_rc is not None:
        return daemon_rc

    _configure_logging_level()
    _configure_stream(log_path)

    cfg = BenchmarkConfig.from_dict(json.loads(config_path.read_text()))
    stop_token = StopToken(stop_file=stop_path)
    runner = LocalRunner(
        cfg,
        registry=create_registry(),
        progress_callback=None,
        host_name=host or "host",
        stop_token=stop_token,
    )

    start = time.time()
    try:
        success = runner.run_benchmark(
            workload,
            repetition_override=repetition,
            total_repetitions=total_reps,
            run_id=run_id,
        )
    except Exception as exc:  # noqa: BLE001
        duration = time.time() - start
        payload = {
            "run_id": run_id,
            "host": host,
            "workload": workload,
            "repetition": repetition,
            "total_repetitions": total_reps,
            "status": "failed",
            "message": f"error={exc} duration={duration:.1f}s",
        }
        print("LB_EVENT " + json.dumps(payload), flush=True)
        _write_status(status_path, 1)
        return 1

    duration = time.time() - start
    if not success:
        payload = {
            "run_id": run_id,
            "host": host,
            "workload": workload,
            "repetition": repetition,
            "total_repetitions": total_reps,
            "status": "failed",
            "message": f"duration={duration:.1f}s",
        }
        print("LB_EVENT " + json.dumps(payload), flush=True)
        _write_status(status_path, 1)
        return 1
    payload = {
        "run_id": run_id,
        "host": host,
        "workload": workload,
        "repetition": repetition,
        "total_repetitions": total_reps,
        "status": "done",
        "message": f"duration={duration:.1f}s",
    }
    print("LB_EVENT " + json.dumps(payload), flush=True)
    _write_status(status_path, 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
