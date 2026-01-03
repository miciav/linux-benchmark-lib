# DFaaS Event Streaming Status (v0.62.0)

## Summary
We still do not see runner/k6 `LB_EVENT` entries in the TUI dashboard during live
execution. The polling loop noise has been reduced, but the event stream panel
remains empty or only shows task status lines.

## What Works
- DFaaS runs complete and k6 outputs are written to `k6.log` on the generator.
- The workload runner emits task lines in the dashboard (setup/run phases).
- Polling noise has been collapsed into a single “Polling loop …” line.

## What Does Not Work
- Live `LB_EVENT` lines are not appearing in the dashboard while the run is active.
- This includes:
  - LocalRunner progress/status events.
  - k6 log stream events emitted by the DFaaS generator.

## Relevant Data Paths
1) LocalRunner emits `LB_EVENT` to stdout.
2) `async_localrunner` tees stdout into `lb_events.stream.log`.
3) `stream_events_step.yml` reads the stream file and prints `LB_EVENT` lines.
4) Controller output pipeline parses `LB_EVENT` and updates the dashboard.

The above chain is still not producing visible events in the TUI.

## Changes Already Applied
- Event logging defaults to ON (only disabled by `LB_ENABLE_EVENT_LOGGING=0`).
- DFaaS k6 log events are emitted as `LB_EVENT` by the generator.
- Polling loop is summarized in-place in the dashboard.
- Polling task now prints `LB_EVENT` lines as text (not raw bytes).
- Event tailer now avoids Python 3.13 `tell()` iteration issues.

## Current Hypothesis
The dashboard is not receiving any `LB_EVENT` lines from the controller output
stream, even though they should be emitted by LocalRunner and k6.

Possible causes:
- The stream log file is empty or contains no `LB_EVENT`.
- The polling task is not printing the `LB_EVENT` lines to stdout.
- Parsing fails in `_extract_lb_event_data` due to formatting/wrapping.
- The event tailer or dedupe drops entries before they reach the dashboard.

## Next Diagnostic Steps
1) Confirm `lb_events.stream.log` on target contains `LB_EVENT` lines.
2) Confirm polling task prints them by capturing raw controller output.
3) Feed a captured line into `_extract_lb_event_data` and `parse_progress_line`.
4) Temporarily inject a synthetic `LB_EVENT` line in `stream_events_step.yml`
   and verify it appears in the dashboard.

## Status
As of this version, event streaming to the dashboard is **not resolved**.
This document records the unresolved state so future investigation can resume
from the correct assumptions.
