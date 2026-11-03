#!/usr/bin/env python3
"""island.history.HistoryFeed contract (Stage 2 seam, dormant)."""
import island.history


class TestAppendAndBasics:
    def test_empty_snapshot_and_len(self):
        feed = island.history.HistoryFeed()
        assert len(feed) == 0
        assert feed.snapshot() == ()

    def test_append_order_oldest_first(self):
        feed = island.history.HistoryFeed()
        for i in range(3):
            feed.append({"n": i})
        snap = feed.snapshot()
        assert [e["n"] for e in snap] == [0, 1, 2]
        assert len(feed) == 3

    def test_default_maxlen_is_200(self):
        feed = island.history.HistoryFeed()
        for i in range(205):
            feed.append({"n": i})
        snap = feed.snapshot()
        assert len(snap) == 200
        # oldest-first eviction: entries 0..4 dropped, 5..204 kept in order
        assert snap[0]["n"] == 5
        assert snap[-1]["n"] == 204

    def test_explicit_maxlen(self):
        feed = island.history.HistoryFeed(maxlen=2)
        feed.append("a")
        feed.append("b")
        feed.append("c")
        assert feed.snapshot() == ("b", "c")
        assert len(feed) == 2


class TestSnapshotIsolation:
    def test_snapshot_is_defensive_copy(self):
        feed = island.history.HistoryFeed(maxlen=5)
        event = {"a": [1, 2], "b": {"c": 3}, "d": "plain"}
        feed.append(event)
        snap = feed.snapshot()
        assert snap[0] is not event            # outer object copied

    def test_mutating_returned_nested_entries_never_touches_history(self):
        feed = island.history.HistoryFeed(maxlen=5)
        feed.append({"a": [1, 2], "b": {"c": 3}, "d": "plain"})
        snap = feed.snapshot()
        snap[0]["a"].append(999)
        snap[0]["b"]["c"] = "mutated"
        snap[0]["d"] = "mutated"
        snap2 = feed.snapshot()
        assert snap2[0] == {"a": [1, 2], "b": {"c": 3}, "d": "plain"}
        assert len(snap2) == 1

    def test_append_stores_by_reference_snapshots_copy_on_read(self):
        # Approved contract: isolation is guaranteed on the READ side
        # (snapshot deep-copies). Storage is by reference, so out-of-band
        # mutation of the caller's event object after append is visible on
        # the next snapshot — recorded here as the documented behaviour.
        feed = island.history.HistoryFeed(maxlen=5)
        event = {"a": [1]}
        feed.append(event)
        event["a"].append(42)
        assert feed.snapshot()[0] == {"a": [1, 42]}
