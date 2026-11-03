#!/usr/bin/env python3
"""island.peek pure-helper contract (Stage 2)."""
import inspect

import island.peek
import island_pill


class TestShouldShowPeekTruthTable:
    def test_full_matrix(self):
        f = island.peek.should_show_peek
        # (is_open, peeks_enabled) -> may display now?
        assert f(True, True) is False      # never display over an open card
        assert f(True, False) is False     # defensive completeness
        assert f(False, True) is True      # display branch
        assert f(False, False) is False    # drop silently

    def test_falsy_peeks_values(self):
        f = island.peek.should_show_peek
        assert f(False, 0) is False
        assert f(False, 1) is True
        assert f(False, "yes") is True

    def test_signature_is_decision_only(self):
        params = list(inspect.signature(island.peek.should_show_peek).parameters)
        assert params == ["is_open", "peeks_enabled"]


class TestCleanNotifText:
    def test_strips_tags(self):
        assert island.peek.clean_notif_text("<b>Hello</b> world") == "Hello world"

    def test_unescapes_entities_before_stripping_order_ok(self):
        assert island.peek.clean_notif_text("A &amp; B") == "A & B"

    def test_collapses_newlines_and_trims(self):
        assert island.peek.clean_notif_text("line one\nline two\n") == "line one line two"

    def test_empty_and_none_inputs(self):
        assert island.peek.clean_notif_text("") == ""
        assert island.peek.clean_notif_text(None) == ""

    def test_matches_on_notify_original_shape(self):
        # Composition relevance: on_notify uses it to derive summary/body;
        # a fully-HTML notification loses its markup entirely.
        assert island.peek.clean_notif_text("<i>Track</i>") == "Track"


class TestIsDuplicateNotif:
    def test_same_payload_within_window(self):
        last = ("a\0b", 100.0)
        assert island.peek.is_duplicate_notif(last, 101.5, "a", "b") is True

    def test_same_payload_after_window(self):
        last = ("a\0b", 100.0)
        assert island.peek.is_duplicate_notif(last, 103.0, "a", "b") is False

    def test_different_payload(self):
        last = ("a\0b", 100.0)
        assert island.peek.is_duplicate_notif(last, 100.5, "c", "d") is False

    def test_window_parameterised(self):
        last = ("a\0b", 100.0)
        assert island.peek.is_duplicate_notif(last, 105.0, "a", "b", window=10.0) is True


class TestPeekQueuePayload:
    def test_all_fields_present(self):
        payload = island.peek.peek_queue_payload("timer", "Time's up", "5 min",
                                                 10, "optional", "app1")
        assert payload == {"kind": "timer", "title": "Time's up", "body": "5 min",
                           "secs": 10, "accent": "optional", "app": "app1"}

    def test_none_fields_kept(self):
        payload = island.peek.peek_queue_payload("bt", "Dev", "", 4, None, "")
        assert payload["accent"] is None and payload["app"] == ""


class TestPublicSurfaceNotShadowed:
    """Island.show_peek stays the public entry; the pure helper is not
    exposed on Island (anti-accidental-replacement safeguards)."""

    def test_island_has_no_pure_helper(self):
        assert not hasattr(island_pill.Island, "should_show_peek")

    def test_public_show_peek_signature_unchanged(self):
        sig = inspect.signature(island_pill.Island.show_peek)
        assert [p for p in sig.parameters] == [
            "self", "kind", "title", "body", "secs", "accent", "app"]
        assert sig.parameters["body"].default == ""
        assert sig.parameters["secs"].default is None
        assert sig.parameters["accent"].default is None
        assert sig.parameters["app"].default == ""
