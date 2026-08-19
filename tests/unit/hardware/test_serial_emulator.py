"""Tests for the in-process serial emulator (and the broker's await/timeout pattern)."""

from __future__ import annotations

import time

from sorter.hardware.serial_emulator import EmulatorBroker


def test_emulator_feed_one_returns_done() -> None:
    em = EmulatorBroker(response_delay_s=0.01)
    em.try_open()
    assert em.feed_one() is True


def test_emulator_sort_returns_done() -> None:
    em = EmulatorBroker(response_delay_s=0.01)
    em.try_open()
    assert em.sort_and_move(3) is True


def test_emulator_get_config_returns_dict() -> None:
    em = EmulatorBroker(response_delay_s=0.01)
    em.try_open()
    cfg = em.get_config(timeout_s=1.0)
    assert isinstance(cfg, dict)
    assert "feedspeed" in cfg


def test_emulator_fires_on_sent_for_every_command() -> None:
    em = EmulatorBroker(response_delay_s=0.01)
    em.try_open()
    seen: list[str] = []
    em.on_sent.append(seen.append)
    em.send_command("ping")
    em.send_command("xf:0")
    # Give the timer thread a tick to dispatch the response so it doesn't blow up.
    time.sleep(0.05)
    assert "ping" in seen
    assert "xf:0" in seen


def test_emulator_update_init_settings_pushes_each_key() -> None:
    em = EmulatorBroker(response_delay_s=0.01)
    em.try_open()
    seen: list[str] = []
    em.on_sent.append(seen.append)
    em.update_init_settings({"feedspeed": 60, "airdropenabled": True})
    # Allow the timer thread to drain.
    time.sleep(0.1)
    assert "feedspeed:60" in seen
    assert "airdropenabled:1" in seen


# ----- disconnect parity (issue #35) ------------------------------------------


def test_simulate_disconnect_announces_once() -> None:
    em = EmulatorBroker(response_delay_s=0.01)
    em.try_open()
    reasons: list[str] = []
    em.on_disconnect.append(reasons.append)

    em.simulate_disconnect("cable pulled")
    em.simulate_disconnect("cable pulled again")

    assert reasons == ["cable pulled"]
    assert em.is_connected is False


def test_stop_announces_nothing() -> None:
    # Parity with SerialBroker: a stop we asked for is not a disconnect.
    em = EmulatorBroker(response_delay_s=0.01)
    em.try_open()
    reasons: list[str] = []
    em.on_disconnect.append(reasons.append)
    em.stop()
    assert reasons == []


def test_a_pulled_cable_fails_the_next_sort_immediately() -> None:
    em = EmulatorBroker(response_delay_s=0.01)
    em.try_open()
    em.simulate_disconnect()

    started = time.monotonic()
    assert em.sort_and_move(3) is False
    # Would otherwise sit out the 20s sort timeout.
    assert time.monotonic() - started < 1.0
