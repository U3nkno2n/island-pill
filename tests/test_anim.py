#!/usr/bin/env python3
"""island.anim contract (Stage 3): the pure spring and visual-phase math."""
import math

import pytest

import island.anim as anim


def test_spring_axis_settles_in_one_step_keeps_verbatim_literals():
    # |tgt-cur| < 0.3 and |vel| < 2.0 -> snap to (float(tgt), 0.0, True):
    # the exact on_tick settle branch.
    assert anim.spring_axis(99.9, 1.0, 100.0, 1 / 60.0) == (100.0, 0.0, True)


def test_spring_axis_oscillation_then_settle():
    cur, vel, tgt, dt = 8.0, 0.0, 240.0, 1 / 60.0
    for _ in range(400):
        cur, vel, settled = anim.spring_axis(cur, vel, tgt, dt)
        if settled:
            break
    assert settled
    assert (cur, vel) == (240.0, 0.0)


def test_spring_axis_one_step_reproduces_original_formula():
    # Independent recomputation of the verbatim literals (k=220, d=31).
    cur, vel, tgt, dt = 10.0, 2.0, 20.0, 1 / 30.0
    exp_v = vel + (220.0 * (tgt - cur) - 31.0 * vel) * dt
    exp_cur = cur + exp_v * dt
    exp_settled = abs(tgt - exp_cur) < 0.3 and abs(exp_v) < 2.0
    got = anim.spring_axis(cur, vel, tgt, dt)
    assert got == (exp_cur, exp_v, exp_settled)


def test_advance_music_increment_and_wrap():
    assert anim.advance_music(0.0) == 0.22
    assert anim.advance_music(2 * math.pi - 0.22) == pytest.approx(0.0)
    assert anim.advance_music(2 * math.pi - 0.10) == pytest.approx(0.12)


def test_advance_dl_phase_bounces_at_bounds():
    assert anim.advance_dl_phase(0.999, 1.0) == (1.0, -1.0)   # crossed top
    assert anim.advance_dl_phase(0.97, 1.0) == (pytest.approx(0.988), 1.0)   # inside
    assert anim.advance_dl_phase(0.001, -1.0) == (0.0, 1.0)   # crossed bottom
    assert anim.advance_dl_phase(0.02, -1.0) == (pytest.approx(0.002), -1.0)  # inside


def test_advance_charge_wraps_unit_interval():
    assert anim.advance_charge(0.9) == pytest.approx(0.945)
    assert anim.advance_charge(0.97) == pytest.approx(0.015)


def test_ease_battery_matches_original_branch_semantics():
    # Exponential easing: no overshoot beyond the actual percentage, and the
    # original else-branch did NOT mark the tick active on settle.
    assert anim.ease_battery(9.95, 10.05) == (10.05, False)   # |diff| 0.1 <= 0.15
    value, active = anim.ease_battery(8.0, 10.0)              # diff 2.0 -> +20%
    assert value == 8.4 and active is True
