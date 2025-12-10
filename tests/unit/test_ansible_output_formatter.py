from lb_controller.services.run_service import AnsibleOutputFormatter


def test_task_parsing_with_nested_brackets():
    formatter = AnsibleOutputFormatter()
    captured: list[str] = []

    line = (
        "TASK [workload_runner : [run:lb-worker-1a003223] "
        "Prepare benchmark configuration for this host] *********************"
    )

    formatter.process(line, log_sink=captured.append)

    assert captured == [
        "• \\[run-lb-worker-1a003223] Prepare benchmark configuration for this host"
    ]


def test_progress_parsing_from_raw_lb_event():
    formatter = AnsibleOutputFormatter()
    captured: list[str] = []

    line = (
        'LB_EVENT {"run_id": "run-1", "host": "h1", '
        '"workload": "fio", "repetition": 1, "total_repetitions": 3, "status": "running"}'
    )

    formatter.process(line, log_sink=captured.append)

    assert captured == ["• \\[run-h1-fio] 1/3 running"]


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

    assert captured == ["• \\[run-lb-worker-1a003223-fio] 1/3 running"]


def test_progress_parse_helper_used_by_run_service():
    from lb_controller.services.run_service import RunService

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
    }


def test_slug_phase_collapses_multiple_dash():
    formatter = AnsibleOutputFormatter()
    assert formatter._slug_phase("run::host  workload") == "run-host-workload"
