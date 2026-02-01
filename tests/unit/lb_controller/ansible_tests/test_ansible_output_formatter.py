from lb_app.api import AnsibleOutputFormatter
import pytest


@pytest.mark.unit_controller
def test_task_parsing_with_nested_brackets():
    formatter = AnsibleOutputFormatter()
    formatter.emit_task_starts = True
    captured: list[str] = []

    line = (
        "TASK [workload_runner : [run:lb-worker-1a003223] "
        "Prepare benchmark configuration for this host] *********************"
    )

    formatter.process(line, log_sink=captured.append)

    assert captured == [
        "• \\[run-lb-worker-1a003223] Prepare benchmark configuration for this host"
    ]


@pytest.mark.unit_controller
def test_progress_parsing_from_raw_lb_event():
    formatter = AnsibleOutputFormatter()
    captured: list[str] = []

    line = (
        'LB_EVENT {"run_id": "run-1", "host": "h1", '
        '"workload": "fio", "repetition": 1, "total_repetitions": 3, "status": "running"}'
    )

    formatter.process(line, log_sink=captured.append)

    assert captured == ["• \\[run-fio] (h1) 1/3 running"]


@pytest.mark.unit_controller
def test_progress_parsing_from_ansible_debug_wrapped_event():
    formatter = AnsibleOutputFormatter()
    captured: list[str] = []
    # Matches ansible debug output where the LB_EVENT payload is quoted and escaped
    line = (
        'ok: [lb-worker-1a003223] => {"msg": "LB_EVENT '
        '{\\"run_id\\": \\"run-20251210-132026\\", '
        '\\"host\\": \\"lb-worker-1a003223\\", '
        '\\"workload\\": \\"fio\\", '
        '\\"repetition\\": 1, '
        '\\"total_repetitions\\": 3, '
        '\\"status\\": \\"running\\"}"}'
    )

    formatter.process(line, log_sink=captured.append)

    assert captured == ["• \\[run-fio] (lb-worker-1a003223) 1/3 running"]


@pytest.mark.unit_controller
def test_progress_parse_helper_used_by_run_service():
    from lb_app.api import RunService

    svc = RunService(lambda: None)
    line = (
        'ok: [lb-worker-1a003223] => {"msg": "LB_EVENT '
        '{\\"run_id\\": \\"run-20251210-132026\\", '
        '\\"host\\": \\"lb-worker-1a003223\\", '
        '\\"workload\\": \\"fio\\", '
        '\\"repetition\\": 2, '
        '\\"total_repetitions\\": 3, '
        '\\"status\\": \\"running\\"}"}'
    )

    info = svc._parse_progress_line(line)

    assert info == {
        "host": "lb-worker-1a003223",
        "workload": "fio",
        "rep": 2,
        "status": "running",
        "total": 3,
        "message": None,
        "type": "status",
        "level": "INFO",
        "error_type": None,
        "error_context": None,
    }


@pytest.mark.unit_controller
def test_slug_phase_collapses_multiple_dash():
    formatter = AnsibleOutputFormatter()
    assert formatter._slug_phase("run::host  workload") == "run-host-workload"


@pytest.mark.unit_controller
def test_task_timing_from_lb_task_event():
    formatter = AnsibleOutputFormatter()
    captured: list[str] = []

    line = (
        'LB_TASK {"host": "h1", "task": "workload_runner : [run:dd] Execute dd repetition 1", '
        '"duration_s": 2.5}'
    )

    formatter.process(line, log_sink=captured.append)

    assert captured == ["• \\[run-dd] (h1) Execute dd repetition 1 done in 2.5s"]


@pytest.mark.unit_controller
def test_msg_line_parsing_from_ansible_debug():
    formatter = AnsibleOutputFormatter()
    formatter.set_phase("Global Setup")
    formatter.host_label = "h1"
    captured: list[str] = []

    line = '"msg": "Workload runner mode=execute tests=[\\"dd\\"]"'

    formatter.process(line, log_sink=captured.append)

    assert captured == [
        "• \\[global-setup] (h1) Workload runner mode=execute tests=[\"dd\"]"
    ]
