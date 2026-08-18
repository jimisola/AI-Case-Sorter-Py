"""Tests for the training subprocess manager.

Uses a stub training script (not the real torch-backed one) so the tests are
fast and require no GPU/torch install.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sorter.control.events import EventBus
from sorter.data.models import TrainingConfig
from sorter.training.manager import TrainingJob, TrainingManager, build_command


def _write_stub(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _collect(bus: EventBus, topic: str, sink: list) -> None:
    bus.subscribe(topic, lambda payload: sink.append(payload))


def _run(
    tmp_path: Path, script_body: str, *, cfg_overrides: dict | None = None
) -> tuple[TrainingManager, EventBus, dict[str, list]]:
    bus = EventBus()
    sinks: dict[str, list] = {
        "start": [],
        "epoch": [],
        "done": [],
        "log": [],
        "error": [],
        "failed": [],
        "cancelled": [],
    }
    for k in sinks:
        _collect(bus, f"training/{k}", sinks[k])

    script = _write_stub(tmp_path / "stub_train.py", script_body)
    cfg = TrainingConfig()
    for k, v in (cfg_overrides or {}).items():
        setattr(cfg, k, v)

    job = TrainingJob(
        image_dir=tmp_path / "imgs",
        output_model=tmp_path / "out.pth",
        config=cfg,
    )
    mgr = TrainingManager(bus)
    mgr.spawn(job, script=script)
    mgr.wait(timeout=30)
    # Pump bus once so subscribers receive everything.
    bus.drain(max_items=256)
    return mgr, bus, sinks


def test_build_command_includes_all_required_flags(tmp_path: Path) -> None:
    cfg = TrainingConfig(model_name="convnext_base", epochs=5, batch_size=8, use_swa=True)
    job = TrainingJob(image_dir=tmp_path / "imgs", output_model=tmp_path / "out.pth", config=cfg)
    cmd = build_command(job)
    assert "--model_name" in cmd and "convnext_base" in cmd
    assert "--epochs" in cmd and "5" in cmd
    assert "--use_swa" in cmd


def test_progress_markers_dispatch_to_bus_topics(tmp_path: Path) -> None:
    script_body = """
        import json, sys
        def emit(event, **payload):
            payload["event"] = event
            sys.stdout.write("[PROGRESS] " + json.dumps(payload) + chr(10))
            sys.stdout.flush()
        emit("start", epochs=2, classes=3, images=10)
        emit("epoch", epoch=1, train_loss=0.5, train_acc=0.7, val_acc=0.6)
        emit("epoch", epoch=2, train_loss=0.3, train_acc=0.8, val_acc=0.7)
        emit("done", best_val_acc=0.7, best_val_loss=0.3)
    """
    mgr, _, sinks = _run(tmp_path, script_body)
    assert len(sinks["start"]) == 1 and sinks["start"][0]["epochs"] == 2
    assert len(sinks["epoch"]) == 2
    assert sinks["epoch"][1]["epoch"] == 2
    assert len(sinks["done"]) == 1
    assert mgr.last_result() == {"best_val_acc": 0.7, "best_val_loss": 0.3}


def test_non_progress_stdout_goes_to_log(tmp_path: Path) -> None:
    script_body = """
        import sys
        print("hello world", flush=True)
        print("[PROGRESS] not json{", flush=True)
        print("[PROGRESS] " + '{"event":"done"}', flush=True)
    """
    _, _, sinks = _run(tmp_path, script_body)
    # "hello world" goes to log; the malformed progress line is *also* logged.
    log_lines = [s for s in sinks["log"] if s]
    assert "hello world" in log_lines
    assert any("not json{" in s for s in log_lines)
    assert len(sinks["done"]) == 1


def test_nonzero_exit_emits_failed(tmp_path: Path) -> None:
    script_body = """
        import sys
        sys.stderr.write("kaboom" + chr(10))
        sys.exit(7)
    """
    _, _, sinks = _run(tmp_path, script_body)
    assert any("kaboom" in s for s in sinks["error"])
    assert len(sinks["failed"]) == 1
    assert sinks["failed"][0]["return_code"] == 7


def test_cancel_emits_cancelled(tmp_path: Path) -> None:
    import time

    script_body = """
        import time, sys
        sys.stdout.write("[PROGRESS] " + '{"event":"start","epochs":99}' + chr(10))
        sys.stdout.flush()
        # Sleep long enough that cancel() arrives first
        time.sleep(30)
    """
    bus = EventBus()
    sinks: dict[str, list] = {"cancelled": [], "start": []}
    for k in sinks:
        _collect(bus, f"training/{k}", sinks[k])
    script = _write_stub(tmp_path / "stub.py", script_body)
    mgr = TrainingManager(bus)
    mgr.spawn(
        TrainingJob(
            image_dir=tmp_path / "imgs",
            output_model=tmp_path / "out.pth",
            config=TrainingConfig(),
        ),
        script=script,
    )
    # Wait for the start marker to confirm the child is running.
    deadline = time.time() + 5
    while time.time() < deadline:
        bus.drain(max_items=64)
        if sinks["start"]:
            break
        time.sleep(0.05)
    assert sinks["start"], "child never emitted start; cannot test cancel"
    mgr.cancel()
    mgr.wait(timeout=10)
    bus.drain(max_items=64)
    assert len(sinks["cancelled"]) == 1


def test_cannot_spawn_two_concurrent_jobs(tmp_path: Path) -> None:
    script_body = """
        import time
        time.sleep(5)
    """
    bus = EventBus()
    script = _write_stub(tmp_path / "stub.py", script_body)
    mgr = TrainingManager(bus)
    job = TrainingJob(
        image_dir=tmp_path / "imgs",
        output_model=tmp_path / "out.pth",
        config=TrainingConfig(),
    )
    mgr.spawn(job, script=script)
    try:
        with pytest.raises(RuntimeError):
            mgr.spawn(job, script=script)
    finally:
        mgr.cancel()
        mgr.wait(timeout=10)


# ----- the run's log file (issue #100) ----------------------------------------


def test_the_run_is_written_to_a_log_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    script_body = """
        import json, sys
        print("[SETUP] PyTorch 9.9.9")
        print("[INFO] Device: CPU")
        sys.stderr.write("a warning" + chr(10))
        sys.stdout.write('[PROGRESS] {"event": "done", "best_val_acc": 0.9}' + chr(10))
    """
    mgr, _, sinks = _run(tmp_path, script_body)

    assert mgr.log_path is not None
    text = mgr.log_path.read_text(encoding="utf-8")
    assert "[SETUP] PyTorch 9.9.9" in text
    assert "[INFO] Device: CPU" in text
    # stderr is in the same file, marked — a traceback is the reason to read it.
    assert "[stderr] a warning" in text
    # The markers are kept verbatim: the file is the console, not a summary.
    assert '[PROGRESS] {"event": "done"' in text
    assert "# exit code: 0" in text
    # And the window is told where it went.
    assert any(str(mgr.log_path) in str(line) for line in sinks["log"])


def test_the_log_file_lands_under_the_data_root(tmp_path: Path, monkeypatch) -> None:
    from sorter import paths

    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    mgr, _, _ = _run(tmp_path, "print('hello')")

    assert mgr.log_path is not None
    assert mgr.log_path.parent == paths.logs_dir()
    assert mgr.log_path.name.startswith("training-")


def test_an_unwritable_log_costs_the_file_not_the_run(tmp_path: Path, monkeypatch) -> None:
    """Same rule the launcher follows: the log is never why a launch fails."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    # A *file* where the logs directory should be: mkdir raises, and nothing
    # downstream may care.
    (data_root / "logs").write_text("in the way", encoding="utf-8")
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(data_root))

    mgr, _, sinks = _run(tmp_path, "print('still ran')")

    assert mgr.log_path is None
    assert any("still ran" in str(line) for line in sinks["log"])


def test_old_training_logs_are_pruned(tmp_path: Path, monkeypatch) -> None:
    from sorter import paths
    from sorter.training import manager as manager_module

    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    logs = paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    for index in range(manager_module.MAX_TRAINING_LOGS + 5):
        (logs / f"training-2020010{index // 10}-0000{index % 10}.log").write_text("old", encoding="utf-8")

    _run(tmp_path, "print('new run')")

    # The pruning happens before the new file is opened, so the new one is extra.
    assert len(manager_module.training_logs()) == manager_module.MAX_TRAINING_LOGS + 1


def test_training_logs_lists_newest_first(tmp_path: Path, monkeypatch) -> None:
    from sorter import paths
    from sorter.training import manager as manager_module

    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    logs = paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    for stamp in ("20260101-000000", "20260301-000000", "20260201-000000"):
        (logs / f"training-{stamp}.log").write_text("x", encoding="utf-8")

    assert [p.name for p in manager_module.training_logs()][0] == "training-20260301-000000.log"
