# Prompt: DFaaS missing LB_EVENT logs (operational checklist)

## Objective
- Reproduce the DFaaS run where the polling loop runs but no `LB_EVENT` lines
  appear.
- Capture on-target evidence before cleanup.
- Identify the cause (likely logging not configured) and propose a fix.

## Preconditions
- Repo: `linux-benchmark-lib`
- Config: `benchmark_config.dfaas_multipass.json`
- VMs: `dfaas-target` (192.168.2.2) and `dfaas-generator` (192.168.2.3)
- Ensure multipass instances are running.

## Checklist — Reproduce
- [ ] Confirm or recreate the multipass VMs (e.g., `scripts/setup_dfaas_multipass.sh`).
- [ ] Start the DFaaS run using the same command as before.
- [ ] Note the run id (from local `benchmark_results/run-*/ui_stream.log`).

## Checklist — Prevent cleanup (so logs persist)
- [ ] Temporarily disable cleanup in `lb_controller/ansible/playbooks/teardown.yml`,
      or add a flag (e.g. `lb_cleanup_enabled=false`) to skip deletion.
- [ ] Re-run the DFaaS benchmark with cleanup disabled.

## Checklist — Collect evidence during the run
On `dfaas-target`:
- [ ] Verify LocalRunner is running:
      `ps aux | grep -E "async_localrunner|lb_runner"`
- [ ] Inspect pid/status:
      `/opt/lb/lb_localrunner.pid`
      `/opt/lb/lb_localrunner.status.json`
- [ ] Confirm generated config exists:
      `/opt/lb/benchmark_config.generated.json`
- [ ] Tail the event stream live:
      `tail -f /tmp/benchmark_results/<run-id>/dfaas-target/lb_events.stream.log`

On `dfaas-generator`:
- [ ] Locate and tail k6 log:
      `/var/lib/dfaas-k6/<target>/<run-id>/<config-id>/k6.log`
- [ ] Verify k6 process is running.

On local controller:
- [ ] Inspect:
      `benchmark_results/<run-id>/run.log`
      `benchmark_results/<run-id>/ui_stream.log`
- [ ] Confirm output dir + workdir match expectations.

## Checklist — Inspect relevant code paths
- [ ] LocalRunner entrypoint: `lb_runner/services/async_localrunner.py`
- [ ] Event log handler: `lb_runner/services/log_handler.py`
- [ ] Runner execution/logging: `lb_runner/engine/runner.py`
- [ ] DFaaS generator: `lb_plugins/plugins/dfaas/generator.py`
- [ ] Polling loop: `lb_controller/ansible/roles/workload_runner/tasks/stream_events_step.yml`

## Hypotheses to validate
- [ ] Logging level is too high (default WARNING), so `logger.info` events never
      appear in `lb_events.stream.log`.
- [ ] LocalRunner crashes before emitting events (check status file + stderr).
- [ ] `LB_EVENT_STREAM_PATH` or permissions are wrong.
- [ ] Cleanup removed evidence before inspection.

## Fix candidates
- [ ] Ensure INFO logging for the LocalRunner:
      - Set `LB_LOG_LEVEL=INFO` in the Ansible task env, or
      - Call `lb_common.configure_logging()` early in
        `lb_runner/services/async_localrunner.py`.
- [ ] Make cleanup conditional to preserve logs for debugging.
- [ ] (Optional) Add debug output in `stream_events_step.yml` if the log file
      is missing or empty.

## Expected outcome
- `lb_events.stream.log` contains `LB_EVENT` lines from LocalRunner and k6.
- Polling loop detects `status=done` or `status=failed` and exits normally.
