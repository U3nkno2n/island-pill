"""Pure clock/time formatting helpers.

Extracted verbatim from island_pill.py (Stage 1, Phase 2 restructure).
This module owns no application configuration: callers pass the hour
format explicitly. It imports only the standard library, keeping the
package import-safe without GTK/GLib.
"""
import time


def fmt_mmss(secs):
    return "%d:%02d" % (secs // 60, secs % 60)


def clock_text(hour24=False):
    if hour24:
        return time.strftime("%H:%M")
    return time.strftime("%I:%M %p").lstrip("0")
