"""Stop coordination helpers for the benchmark controller."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict

from lb_controller.engine.run_state import RunFlags
from lb_controller.models.state import ControllerState
from lb_controller.engine.stops import StopState
from lb_controller.models.types import InventorySpec
from lb_controller.services.services import ControllerServices
from lb_controller.engine.session import RunSession


def handle_stop_during_workloads(
    services: ControllerServices,
    session: RunSession,
    inventory: InventorySpec,
    extravars: Dict[str, Any],
    flags: RunFlags,
    ui_log: Callable[[str], None],
) -> RunFlags:
    """Arm stop state and execute the stop protocol."""
    services.lifecycle.arm_stop()
    services.lifecycle.mark_waiting_runners()
    session.transition(
        ControllerState.STOPPING_WAIT_RUNNERS,
        reason="stop during workloads",
    )
    flags.stop_protocol_attempted = True
    flags.stop_successful = handle_stop_protocol(
        services, session, inventory, extravars, ui_log
    )
    flags.all_tests_success = False
    return flags


def handle_stop_protocol(
    services: ControllerServices,
    session: RunSession,
    inventory: InventorySpec,
    extravars: Dict[str, Any],
    log_fn: Callable[[str], None],
) -> bool:
    """
    Execute the distributed stop protocol.

    Returns:
        True if stop was confirmed by all runners (safe to teardown).
        False if stop timed out or failed (unsafe to teardown).
    """
    if not session.coordinator:
        return False

    log_fn("Stop confirmed; initiating distributed stop protocol...")
    session.transition(ControllerState.STOPPING_WAIT_RUNNERS)
    session.coordinator.initiate_stop()
    services.lifecycle.mark_waiting_runners()

    stop_pb_content = """
- hosts: all
  gather_facts: true
  become: true
  tasks:
    - name: Create STOP file
      ansible.builtin.file:
        path: "{{ lb_workdir }}/STOP"
        state: touch
        mode: '0644'
"""

    log_fn("Sending stop signal to remote runners...")
    with tempfile.TemporaryDirectory(prefix="lb-stop-protocol-") as tmp_dir:
        stop_pb_path = Path(tmp_dir) / "stop_workload.yml"
        stop_pb_path.write_text(stop_pb_content, encoding="utf-8")
        res = services.executor.run_playbook(
            stop_pb_path,
            inventory=inventory,
            extravars=extravars,
            cancellable=False,
        )

    if not res.success:
        log_fn("Failed to send stop signal (playbook failure).")

    log_fn("Waiting for runners to confirm stop...")

    while True:
        session.coordinator.check_timeout()
        if session.coordinator.state == StopState.TEARDOWN_READY:
            log_fn("All runners confirmed stop.")
            services.lifecycle.mark_stopped()
            session.transition(
                ControllerState.STOPPING_TEARDOWN, reason="runners stopped"
            )
            return True
        if session.coordinator.state == StopState.STOP_FAILED:
            log_fn("Stop protocol timed out or failed.")
            services.lifecycle.mark_failed()
            session.transition(
                ControllerState.STOP_FAILED, reason="stop confirmations timed out"
            )
            return False

        time.sleep(0.5)
