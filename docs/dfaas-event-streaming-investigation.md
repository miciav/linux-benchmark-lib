# DFaaS Event Streaming: Missing Events in Dashboard

## Goal
Make k6 and runner events appear in the TUI dashboard Log Stream and Event Status
without requiring manual env var setup.

## Expected Behavior
- LocalRunner emits `LB_EVENT` lines while the workload runs.
- These events are ingested by the controller pipeline and shown in the dashboard.
- k6 log lines are emitted as `LB_EVENT` (type=log) and appear in the dashboard.
- Polling loop should not drown out event logs.

## Current Observations
- Dashboard still does not show events (runner/k6), even after reducing polling noise.
- Polling tasks are now summarized in-place as a single line ("Polling loop ...").
- k6 log stream works on the generator (k6.log exists and is updated).

## Event Flow (How It Should Work)
1) **LocalRunner (target)** runs `lb_runner.services.async_localrunner`.
2) LocalRunner logs via `LBEventLogHandler` (default enabled), writing `LB_EVENT` lines to stdout.
3) Async LocalRunner tee writes stdout to `lb_events.stream.log`.
4) Ansible task `stream_events_step.yml` reads `lb_events.stream.log` and prints `LB_EVENT` lines to stdout.
5) Controller pipeline parses those `LB_EVENT` lines and converts them to `RunEvent` objects.
6) Dashboard receives `RunEvent` and displays a summary line in Log Stream.

Additional k6 path:
- `DfaasGenerator` calls `K6Runner`.
- `K6Runner` streams k6 log and calls `_emit_k6_log_event`.
- `_emit_k6_log_event` emits `LB_EVENT` log events using `StdoutEmitter`.

## Key Files
- `lb_controller/ansible/roles/workload_runner/tasks/run_single_rep.yml`
- `lb_controller/ansible/roles/workload_runner/tasks/stream_events_step.yml`
- `lb_runner/services/async_localrunner.py`
- `lb_runner/engine/runner.py` (attaches `LBEventLogHandler`)
- `lb_plugins/plugins/dfaas/generator.py` (emits k6 log events)
- `lb_app/services/run_pipeline.py` (ingests LB_EVENT lines)
- `lb_app/services/run_output.py` (formatter; skips raw LB_EVENT output)
- `lb_ui/tui/system/components/dashboard.py` (Log Stream rendering)

## Recent Behavior Changes (Relevant)
- Event logging now defaults to ON. Only `LB_ENABLE_EVENT_LOGGING=0/false/no`
  disables it.
- k6 log lines are now emitted as `LB_EVENT` by `DfaasGenerator`.
- Polling loop logs are summarized into a single line in the dashboard.

## Why Events Might Still Be Missing (Hypotheses)
1) **Event ingestion never sees LB_EVENT lines**
   - `stream_events_step.yml` reads the wrong file or wrong host.
   - The stream file is empty or contains no `LB_EVENT` lines.
   - The stream file is written, but the polling task never prints them.
2) **Event parsing is skipped**
   - Output line wrapping/escaping prevents `_extract_lb_event_data` from
     finding the token.
   - `parse_progress_line` rejects the payload (missing required fields).
3) **Events are dropped by dedupe**
   - `_EventDedupe` uses `(host, workload, repetition, status, type, message)`.
     If the message is repeated exactly, events are dropped.
4) **Dashboard refresh path not hit**
   - `make_output_tee` not wired for the dashboard session in the current run
     mode, or dashboard refresh throttled.
5) **k6 events emitted but not associated to current repetition**
   - Incorrect `repetition` or `total_repetitions` values in emitted events can
     cause events to be ignored or not reflected in the journal.

## Diagnostics Checklist
Run in order and capture evidence:

1) Verify the stream file exists and contains `LB_EVENT` lines on the target:
   - On target: `tail -n 50 /tmp/lb_events.stream.log`
2) Verify the polling task is printing those lines:
   - Add temporary `debug` in `stream_events_step.yml` to print how many
     LB_EVENT lines were read in each iteration (or print the last line offset).
3) Verify the controller sees `LB_EVENT` in its raw output log:
   - Inspect the controller log file (if enabled) for `LB_EVENT` markers.
4) Verify parsing works with real lines:
   - Copy a raw line from the run output and feed it to `_extract_lb_event_data`
     and `parse_progress_line`.
5) Verify the dashboard is in the event pipeline path:
   - Ensure the run is using the TUI (not headless) and that
     `pipeline_output_callback` is used.

## Observed Symptom Patterns to Capture
- `LB_EVENT` lines present in file but not in dashboard.
- `LB_EVENT` lines missing entirely in file.
- `LB_EVENT` lines present but missing required fields or malformed JSON.

## Expected Minimum Signal
During a normal DFaaS run, you should see at least:
- Runner events: "running" and a final "done/failed"
- k6 event lines: `k6[config_id] log stream started`, some stdout lines, and `log stream stopped`

If you do not see these, the issue is likely at steps 1-3 in the event flow.

## Next Suggested Experiments
1) Add a one-time sentinel `LB_EVENT` print in `stream_events_step.yml`
   (after reading the file) to verify the pipeline can display events.
2) Force a synthetic event from `async_localrunner` right after startup
   to confirm ingestion and dashboard rendering.
3) Log the parsed events in `make_progress_handler` before dedupe.

## ROOT CAUSE IDENTIFIED (2026-01-02)

**Bug Location:** `lb_app/services/run_events.py` - `JsonEventTailer._run()`

**Issue:** Python 3.13+ raises `OSError: telling position disabled by next() call`
when calling `fp.tell()` after using the file iterator (`for line in fp`).

**Original Code:**
```python
for line in fp:
    self._pos = fp.tell()  # OSError on Python 3.13+
```

**Fixed Code:**
```python
while True:
    line = fp.readline()
    if not line:
        break
    self._pos = fp.tell()  # Works correctly
```

**Impact:** The `JsonEventTailer` was silently failing to read events from
the callback plugin's JSONL output file (`lb_events.jsonl`), causing all
events to be dropped before reaching the dashboard.

**Fix Applied:** Changed from `for line in fp` iteration to explicit
`fp.readline()` loop to allow `fp.tell()` to work correctly.

## REFINEMENT: Polling Task Suppression (2026-01-03)

**Issue:** After fixing the JsonEventTailer, events appeared in the dashboard
but were drowned out by polling loop task timing lines (Poll LB_EVENT stream,
Delay, Skip polling, etc.).

**Cause:** `AnsibleOutputFormatter._should_suppress_task()` was not suppressing
polling tasks when a dashboard log_sink was active.

**Fix:** Modified `_should_suppress_task()` to always suppress polling loop
tasks regardless of log_sink presence. Added `Initialize polling status` to
the suppress list.

## REFINEMENT: Skip Old Events (2026-01-03)

**Issue:** Events from previous runs appeared at the start of the dashboard
log because `JsonEventTailer` started reading from position 0 (beginning of
the `lb_events.jsonl` file).

**Fix:** Modified `JsonEventTailer.start()` to initialize `_pos` to the
current file size, so only events written after the tailer starts are read.

