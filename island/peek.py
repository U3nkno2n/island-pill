"""Pure peek-notification decisions for Island Pill.

Extracted verbatim from island_pill.py (Stage 2, Phase 2 restructure).
This module owns no state and calls no GLib: the host keeps all peek
state (peek / peek_on / pending_peek) and all timers. Helpers are
parameterised so they never read island_pill or island.settings globals.
"""
import html
import re


def clean_notif_text(s):
    """Verbatim body of on_notify's clean lambda: strip HTML tags and
    unescape entities, collapse newlines to spaces, trim whitespace."""
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).replace("\n", " ").strip()


def is_duplicate_notif(last, now, summary, body, window=2.0):
    """Verbatim dedup decision of on_notify: True when the last shown
    notification equals the new summary+body pair within `window` seconds."""
    return last[0] == summary + "\0" + body and now - last[1] < window


def peek_queue_payload(kind, title, body, secs, accent, app):
    """Payload shape stored as Island.pending_peek while the card is open
    (verbatim from show_peek; consumed by the set_open promotion path),
    which also reads these keys with .get(...) fallbacks."""
    return {
        "kind": kind,
        "title": title,
        "body": body,
        "secs": secs,
        "accent": accent,
        "app": app,
    }


def should_show_peek(is_open, peeks_enabled):
    """Display-gate decision of show_peek (decision-only helper).

    The caller handles the queue branch first (when the card is open it
    queues pending_peek and returns), mirroring the original `if self.open:`
    ... `if not HOVER_ONLY_PEEKS:` order; this helper answers the remaining
    question: may a peek be displayed right now?

    Truth table:
      is_open=True,  peeks_enabled=True  -> False  (never display over an open card)
      is_open=True,  peeks_enabled=False -> False  (defensive completeness)
      is_open=False, peeks_enabled=True  -> True   (display branch)
      is_open=False, peeks_enabled=False -> False  (drop silently)
    """
    return bool(peeks_enabled) and not is_open
