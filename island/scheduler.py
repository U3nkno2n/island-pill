"""Scheduling indirection for the island host (Stage 5).

Every GLib.timeout_add / timeout_add_seconds / source_remove call site in
island_pill.py routes through the four primitives below. The wrappers are
pure pass-throughs: the interval argument is evaluated eagerly at the host
call site exactly as before, the returned source id is passed through
untouched, and the callback return protocol (SOURCE_CONTINUE/SOURCE_REMOVE
or truthy/falsy) stays owned by GLib alone -- the wrappers never intercept
callback return values.

Excluded by design (never move here): GLib.idle_add, add_tick_callback,
GLib.unix_signal_add, Gio D-Bus completion callbacks, and Gtk.main() --
lifecycle and event-loop infrastructure of the GTK host.
"""

from gi.repository import GLib  # noqa: E402

VISUAL_TICK_MS = 33
CLOSE_HYSTERESIS_MS = 350
CHARGE_FLASH_MS = 2200
NOTE_CLEAR_MS = 3000
SEC_TICK_S = 1


def once(ms, fn):
    """One-shot delay: registers on GLib.timeout_add, returns the source id."""
    return GLib.timeout_add(ms, fn)


def loop_ms(ms, fn):
    """Repeating beat with millisecond granularity, same source protocol."""
    return GLib.timeout_add(ms, fn)


def loop_seconds(n, fn):
    """Repeating beat with second granularity (timeout_add_seconds)."""
    return GLib.timeout_add_seconds(n, fn)


def cancel(sid):
    """Guarded removal; the host zeroes its stored id after calling this."""
    if sid:
        GLib.source_remove(sid)
