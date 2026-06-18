"""Tests for segmenter.py — IRC anchor detection and log segmentation (no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from segmenter import (
    detect_host,
    find_question_anchors,
    segment_irc_log,
    normalize_text,
    fingerprint,
    get_substantive_entries,
    _extract_keywords,
)


def test_normalize_text_lowercases_and_strips_punctuation():
    assert normalize_text("Hello, WORLD!") == "hello world"
    # \w includes underscore, so hyphens are replaced but underscores are kept.
    assert normalize_text("foo-bar_baz") == "foo bar_baz"
    assert normalize_text("  multiple   spaces  ") == "multiple spaces"


def test_fingerprint_truncates_to_length():
    assert fingerprint("Hello, World!", length=5) == "hello"
    assert fingerprint("Hi", length=50) == "hi"


def test_detect_host_finds_startmeeting_speaker(sample_log):
    assert detect_host(sample_log) == "ryanofsky"


def test_detect_host_returns_none_without_startmeeting():
    log = [{"nick": "alice", "message": "hello"}, {"nick": "bob", "message": "hi"}]
    assert detect_host(log) is None


def test_extract_keywords_removes_stop_words_and_short_words():
    kws = _extract_keywords("How does the wallet export work?")
    # "how", "the" are stop words; "work" is >3 chars and kept; "does" is a stop word
    assert "wallet" in kws
    assert "export" in kws
    assert "work" in kws
    assert "the" not in kws
    assert "how" not in kws


def test_extract_keywords_includes_compound_terms():
    kws = _extract_keywords("Explain the watch-only export behavior")
    assert "watch-only" in kws
    assert "watchonly" in kws


def test_get_substantive_entries_filters_bots_and_trivia(sample_log):
    substantive = get_substantive_entries(sample_log)
    nicks = {e["nick"] for e in substantive}
    assert "corebot" not in nicks  # bot filtered
    messages = {e["message"] for e in substantive}
    assert "#startmeeting" not in messages
    assert "#here" not in messages
    # substantive content remains
    assert any("exportwatchonlywallet" in e["message"] for e in substantive)


def test_find_question_anchors_locates_numbered_questions(sample_log, sample_questions):
    anchors = find_question_anchors(sample_log, sample_questions, "ryanofsky")
    anchor_map = {q_num: idx for idx, q_num in anchors}
    assert set(anchor_map.keys()) == {1, 2}
    # Q1 anchor comes before Q2 anchor in the log
    assert anchor_map[1] < anchor_map[2]
    # Q1 anchor is at the "1. Did you review..." message (index 5)
    assert anchor_map[1] == 5


def test_find_question_anchors_ignores_non_host_messages(sample_log, sample_questions):
    anchors = find_question_anchors(sample_log, sample_questions, "nobody")
    assert anchors == []


def test_segment_irc_log_assigns_entries_between_anchors(sample_log, sample_questions):
    result = segment_irc_log(sample_log, sample_questions, host_nick="ryanofsky")
    segments = result["segments"]
    # Q1 segment spans from its anchor up to Q2's anchor
    assert len(segments[1]) > 0
    assert len(segments[2]) > 0
    # The Q2 anchor message itself belongs to Q2's segment
    q2_messages = [e["message"] for e in segments[2]]
    assert any("keypool" in m for m in q2_messages)
    # Q1 segment contains alice/bob discussion of the export
    q1_messages = [e["message"] for e in segments[1]]
    assert any("exportwatchonlywallet" in m for m in q1_messages)


def test_segment_irc_log_auto_detects_host_when_none_given(sample_log, sample_questions):
    result = segment_irc_log(sample_log, sample_questions, host_nick=None)
    assert result["host_nick"] == "ryanofsky"


def test_segment_irc_log_returns_unanchored_for_missing_questions(sample_log):
    # Three questions but only two are asked in the log.
    questions = [
        {"number": 1, "text": "Did you review the wallet export changes? What did you think?"},
        {"number": 2, "text": "How does the new RPC interact with the keypool?"},
        {"number": 3, "text": "An unanchored question that is never asked verbatim here"},
    ]
    result = segment_irc_log(sample_log, questions, host_nick="ryanofsky")
    assert 3 in result["unanchored_questions"]
    # Every question gets a segment key (possibly empty)
    assert set(result["segments"].keys()) >= {1, 2, 3}
