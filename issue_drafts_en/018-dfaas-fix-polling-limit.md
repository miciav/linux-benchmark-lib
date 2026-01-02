# DFAAS-QUALITY-2: Fix hardcoded polling limit

## Context
The Ansible streaming events polling loop has a hardcoded limit of 100 iterations, which may be insufficient for long-running workloads.

## Goal
Make the polling limit configurable and add timeout-based termination as a fallback.

## Scope
- Make polling limit configurable
- Add timeout-based fallback
- Improve crash detection
- Maintain backward compatibility

## Non-scope
- Changing to push-based model
- WebSocket implementation
- Fundamental architecture changes

## Current State

### run_single_rep.yml (line 76-79)
```yaml
- name: "{{ run_prefix }} Stream LB_EVENT lines (polling loop)"
  ansible.builtin.include_tasks: stream_events_step.yml
  loop: "{{ range(100) | list }}"  # Hardcoded limit
  when: not workload_runner_finished | default(false)
```

### stream_events_step.yml (lines 24-32)
```yaml
crashed = False
if os.path.exists(pid_path) and not os.path.exists(status_path):
    try:
        with open(pid_path, "r") as f:
            pid = f.read().strip()
        if pid.isdigit() and not os.path.exists(f"/proc/{pid}"):  # Linux-only
            crashed = True
```

Problems:
1. 100 iterations × 10s delay = 16.6 minutes max
2. Long-running DFaaS configs can exceed this
3. Crash detection uses `/proc/{pid}` (Linux-specific, doesn't work in containers)
4. No timeout-based fallback

## Proposed Design

### Configurable Polling
```yaml
# run_single_rep.yml
- name: "{{ run_prefix }} Stream LB_EVENT lines (polling loop)"
  ansible.builtin.include_tasks: stream_events_step.yml
  loop: "{{ range(workload_runner_max_poll_iterations | default(360)) | list }}"
  when: not workload_runner_finished | default(false)
```

### Timeout-Based Termination
```yaml
# stream_events_step.yml
- name: "{{ run_prefix }} Check polling timeout"
  ansible.builtin.set_fact:
    workload_runner_poll_start: "{{ workload_runner_poll_start | default(ansible_date_time.epoch) }}"
    workload_runner_poll_elapsed: "{{ (ansible_date_time.epoch | int) - (workload_runner_poll_start | int) }}"

- name: "{{ run_prefix }} Force finish on timeout"
  ansible.builtin.set_fact:
    workload_runner_finished: true
    workload_runner_timeout: true
  when: workload_runner_poll_elapsed | int > (workload_runner_poll_timeout_seconds | default(3600))
```

### Improved Crash Detection
```python
# Cross-platform crash detection
crashed = False
if os.path.exists(pid_path) and not os.path.exists(status_path):
    try:
        with open(pid_path, "r") as f:
            pid = f.read().strip()
        if pid.isdigit():
            # Method 1: /proc (Linux)
            if os.path.exists("/proc") and not os.path.exists(f"/proc/{pid}"):
                crashed = True
            # Method 2: kill -0 (POSIX)
            else:
                import signal
                try:
                    os.kill(int(pid), 0)
                except OSError:
                    crashed = True
    except Exception:
        pass
```

### New Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `workload_runner_max_poll_iterations` | 360 | Max polling iterations |
| `workload_runner_poll_delay` | 10 | Seconds between polls |
| `workload_runner_poll_timeout_seconds` | 3600 | Absolute timeout (1 hour) |

## Partial Objectives + Tests

### Objective 1: Make polling limit configurable
Add variable with sensible default.
**Tests**:
- Manual test: override via extra-vars
- Verify long workloads complete

### Objective 2: Add timeout-based termination
Implement absolute timeout check.
**Tests**:
- Manual test: timeout triggers after configured time
- Verify timeout event emitted

### Objective 3: Improve crash detection
Use POSIX-compatible method.
**Tests**:
- Manual test: detect crashed process on Linux
- Manual test: detect crashed process on macOS
- Verify container compatibility

### Objective 4: Add documentation
Document new variables in role README.
**Tests**:
- Manual review

## Acceptance Criteria
- [ ] Polling limit configurable via variable
- [ ] Timeout-based fallback works
- [ ] Crash detection works on Linux and macOS
- [ ] Backward compatible (same defaults)
- [ ] Long DFaaS runs complete successfully

## Files to Modify
- `lb_controller/ansible/roles/workload_runner/tasks/run_single_rep.yml`
- `lb_controller/ansible/roles/workload_runner/tasks/stream_events_step.yml`
- `lb_controller/ansible/roles/workload_runner/defaults/main.yml` (if exists)

## Dependencies
- None (independent)

## Effort
~2 hours

