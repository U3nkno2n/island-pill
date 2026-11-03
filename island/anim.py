"""Pure animation math moved verbatim from island_pill.py (Stage 3).

Every function here is a stateless, side-effect-free calculation: the host
keeps all scheduling (frame-clock tick callback, the 33 ms visual timer,
timers in island_pill._ids), dt bookkeeping and all state write-backs.
Numbers are the original literals; moving them changes no timing.
"""

import math


def spring_axis(cur, vel, tgt, dt):
    """One axis of the damped size spring (k=220.0, d=31.0: "softer damped
    spring for a smoother, less snappy resize"). Settles when
    |tgt - cur| < 0.3 and |vel| < 2.0. Returns (cur, vel, settled) with the
    verbatim arithmetic of the original on_tick loop body (settled is
    computed from the unclamped values; the max(8.0, cur) floor stays at the
    host's write-back)."""
    k, d = 220.0, 31.0
    vel += (k * (tgt - cur) - d * vel) * dt
    cur += vel * dt
    if abs(tgt - cur) < 0.3 and abs(vel) < 2.0:
        return float(tgt), 0.0, True
    return cur, vel, False


def advance_music(phase):
    return (phase + 0.22) % (2 * math.pi)


def advance_dl_phase(phase, direction):
    phase += 0.018 * direction
    if phase >= 1.0:
        phase, direction = 1.0, -1.0
    elif phase <= 0.0:
        phase, direction = 0.0, 1.0
    return phase, direction


def advance_charge(phase):
    return (phase + 0.045) % 1.0


def ease_battery(draw_pct, target_pct):
    """Exponential easing is smooth and doesn't overshoot the actual
    percentage. Returns (new_draw_pct, still_animating); the still_animating
    flag mirrors the original on_visual_tick branch, which marked the tick
    active only while the easing move happened."""
    diff = target_pct - draw_pct
    if abs(diff) > 0.15:
        draw_pct += diff * 0.20
        return draw_pct, True
    return target_pct, False
