"""Capped in-memory event feed for Island Pill.

Stage 2 seam module, dormant by design: a capped ring (e.g. 200 entries,
with history.jsonl persistence). Later stages (the agent/event feed)
append to it. Wired to nothing in this stage — no behaviour change.

Pure stdlib only (collections, copy); no GTK/GLib; import-safe headless.
"""
from collections import deque
import copy


class HistoryFeed:
    """Oldest-first capped ring of events.

    append(event) stores the event verbatim; when `maxlen` is exceeded,
    the oldest event is evicted first. snapshot() returns a deep defensive
    copy (tuple of newly created dicts/lists/...), so mutating entries of
    a returned snapshot — including nested structures — never affects the
    stored history, and vice versa.
    """

    def __init__(self, maxlen=200):
        self._events = deque(maxlen=maxlen)

    def append(self, event):
        self._events.append(event)

    def snapshot(self):
        return tuple(copy.deepcopy(event) for event in self._events)

    def __len__(self):
        return len(self._events)
