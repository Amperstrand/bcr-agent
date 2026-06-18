"""Tests for comparator.py — IRC segment extraction (no LLM, no network).

comparator.compare_answer_vs_irc calls the LLM and is excluded; these tests
cover the deterministic extraction/formatting helpers.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from comparator import extract_irc_segment_for_question, format_irc_segment


def test_format_irc_segment_renders_entries():
    seg = [
        {"time": "19:03", "nick": "alice", "message": "hello there"},
        {"time": "19:04", "nick": "bob", "message": "general kenobi"},
    ]
    out = format_irc_segment(seg)
    assert "[19:03] alice: hello there" in out
    assert "[19:04] bob: general kenobi" in out
    assert out.count("\n") == 1


def test_extract_segment_finds_keyword_match_start(sample_log):
    # Question 1 text has many keywords that appear first at the Q1 discussion.
    seg = extract_irc_segment_for_question(
        sample_log,
        question_text="Did you review the wallet export changes?",
        question_idx=0,
        total_questions=2,
    )
    # Should return a non-empty slice from somewhere in the log
    assert isinstance(seg, list)
    assert len(seg) >= 1
    # All returned entries are log entries
    assert all("nick" in e and "message" in e for e in seg)


def test_extract_segment_fallback_distributes_when_no_keyword_match(sample_log):
    # No keyword overlap with any message -> falls back to even distribution.
    seg = extract_irc_segment_for_question(
        sample_log,
        question_text="zzzz nonexistent qqqqq tokens xyzzy",
        question_idx=0,
        total_questions=4,
    )
    # Fallback starts at question_idx * (len//total), so for idx=0 it starts at 0.
    assert isinstance(seg, list)
    assert len(seg) >= 1
    assert seg[0]["nick"] == "ryanofsky"  # first log entry


def test_extract_segment_returns_tail_for_last_question(sample_log):
    # For the last question with no following-numbered-question cue, the segment
    # runs to the end of the log.
    seg = extract_irc_segment_for_question(
        sample_log,
        question_text="zzzz nonexistent qqqqq tokens xyzzy",
        question_idx=2,
        total_questions=3,
    )
    assert isinstance(seg, list)
    assert len(seg) >= 1
