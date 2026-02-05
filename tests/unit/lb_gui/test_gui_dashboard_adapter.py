"""Unit tests for GUI dashboard adapter wiring."""

from __future__ import annotations


def test_gui_adapter_initializes_dashboard() -> None:
    from lb_controller.api import RunJournal
    from lb_gui.adapters.gui_ui_adapter import GuiUIAdapter
    from lb_gui.viewmodels.dashboard_vm import GUIDashboardViewModel

    plan = [{"name": "dfaas", "intensity": "low"}]
    journal = RunJournal(run_id="run-1", tasks={})
    vm = GUIDashboardViewModel()

    adapter = GuiUIAdapter(vm)
    adapter.create_dashboard(plan, journal, None)

    assert vm.snapshot is not None
    assert vm.snapshot.run_id == "run-1"
    assert vm.snapshot.plan_rows
