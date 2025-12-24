"""Molecule verification script for controller stop lifecycle (no VM, delegated driver)."""

from controller_stop_runner import run_all_cases  # type: ignore


def main() -> None:
    cases = run_all_cases()
    for name, markers in cases.items():
        print(f"[{name}] {markers}")
        if name == "clean":
            assert markers["success"] is True
            assert markers["setup"] and markers["run_done"] and markers["teardown"]
        elif name == "setup_interrupt":
            assert markers["teardown"], "Teardown must run after setup interruption"
        elif name == "run_interrupt":
            assert markers["setup"]
            assert markers["teardown"], "Teardown must run after run interruption"
        elif name == "teardown_interrupt":
            assert markers["setup"]
            assert markers["teardown"]


if __name__ == "__main__":
    main()
