import pytest

from lb_app.api import RunJournal, RunStatus, TaskState
from lb_app.api import summarize_progress, target_repetitions

pytestmark = [pytest.mark.unit_ui, pytest.mark.unit_ui]


def _tasks(statuses: list[str]) -> dict[int, TaskState]:
    return {
        idx: TaskState(host="h", workload="w", repetition=idx, status=status)
        for idx, status in enumerate(statuses, start=1)
    }


def test_target_repetitions_prefers_metadata() -> None:
    journal = RunJournal(run_id="run-1")
    journal.metadata["repetitions"] = 5
    journal.tasks = {
        "h::w::1": TaskState(host="h", workload="w", repetition=1),
        "h::w::2": TaskState(host="h", workload="w", repetition=2),
    }

    assert target_repetitions(journal) == 5


@pytest.mark.parametrize(
    ("statuses", "target", "expected_status", "expected_progress"),
    [
        ([RunStatus.RUNNING, RunStatus.FAILED], 2, "failed", "1/2"),
        ([RunStatus.COMPLETED, RunStatus.RUNNING], 2, "running", "1/2"),
        ([RunStatus.SKIPPED, RunStatus.SKIPPED], 2, "skipped", "2/2"),
        ([RunStatus.COMPLETED, RunStatus.COMPLETED], 2, "done", "2/2"),
        ([RunStatus.COMPLETED, RunStatus.PENDING], 3, "partial", "1/3"),
        ([RunStatus.PENDING], 1, "pending", "0/1"),
    ],
)
def test_summarize_progress_status_mapping(
    statuses: list[str],
    target: int,
    expected_status: str,
    expected_progress: str,
) -> None:
    tasks = _tasks(statuses)

    status, progress = summarize_progress(tasks, target)

    assert status == expected_status
    assert progress == expected_progress
