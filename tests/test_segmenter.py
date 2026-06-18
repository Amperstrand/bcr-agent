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
    format_segment,
    build_augmented_context,
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


# --- Anchor pattern coverage (verbatim + "first question" + dedup) ---

def test_find_question_anchors_matches_verbatim_question_text():
    log = [
        {"nick": "host", "message": "#startmeeting"},
        # Host restates the full question text verbatim (no number prefix).
        {"nick": "host", "message": "Let's discuss: What is the wallet export RPC really?"},
        {"nick": "guest", "message": "it exports watch-only keys"},
    ]
    questions = [{"number": 1, "text": "What is the wallet export RPC really?"}]
    anchors = find_question_anchors(log, questions, "host")
    assert anchors == [(1, 1)]


def test_find_question_anchors_first_question_cue():
    log = [
        {"nick": "host", "message": "#startmeeting"},
        # No number prefix, but the "first question" cue.
        {"nick": "host", "message": "ok, first question everyone: what is going on here"},
    ]
    questions = [{"number": 1, "text": "what is going on here"}]
    anchors = find_question_anchors(log, questions, "host")
    assert anchors == [(1, 1)]


def test_find_question_anchors_dedupes_repeated_same_question():
    log = [
        {"nick": "host", "message": "#startmeeting"},
        {"nick": "host", "message": "1. What is the wallet design?"},
        {"nick": "host", "message": "1. What is the wallet design? (repeated)"},
    ]
    questions = [{"number": 1, "text": "What is the wallet design?"}]
    anchors = find_question_anchors(log, questions, "host")
    # The same question anchored twice at adjacent indices collapses to one.
    assert len(anchors) == 1
    assert anchors[0][1] == 1


# --- format_segment + build_augmented_context ---

def test_format_segment_renders_entries():
    seg = [
        {"time": "19:03", "nick": "alice", "message": "hello"},
        {"time": "19:04", "nick": "bob", "message": "world"},
    ]
    out = format_segment(seg)
    assert "[19:03] alice: hello" in out
    assert "[19:04] bob: world" in out


def test_build_augmented_context_includes_irc_and_github():
    workshop = {"questions": [{"number": 1, "text": "wallet export design decisions"}]}
    segmentation = {
        "segments": {
            1: [
                {"time": "19:03", "nick": "alice", "message": "the wallet export is reasonable"},
            ]
        }
    }
    comments = [{"body": "The wallet export design looks solid to me"}]
    out = build_augmented_context(workshop, segmentation, 1, github_comments=comments)
    assert "IRC Discussion" in out
    assert "wallet export" in out  # substantive IRC entry rendered
    assert "GitHub PR Comments" in out
    assert "wallet export design" in out  # relevant comment rendered


def test_build_augmented_context_omits_empty_sections():
    workshop = {"questions": [{"number": 1, "text": "nothing relevant here zzzz"}]}
    segmentation = {"segments": {1: []}}
    out = build_augmented_context(workshop, segmentation, 1, github_comments=None)
    # No IRC entries -> no IRC section
    assert "IRC Discussion" not in out
    assert out.strip() == ""


# --- _rebalance_interleaved: the fragile interleaved-questions path (0% covered before) ---

def test_segment_rebalances_interleaved_questions_by_keyword():
    # Host posts Q1 and Q2 back-to-back, then discussion interleaves.
    # After initial anchor splitting Q1 gets a tiny segment and Q2 a huge one,
    # which triggers _rebalance_interleaved to merge + re-split by keyword.
    log = [
        {"time": "19:00", "nick": "host", "message": "#startmeeting"},
        {"time": "19:01", "nick": "host", "message": "1. What about the wallet design?"},
        {"time": "19:01", "nick": "host", "message": "2. What about the network behavior?"},
        {"time": "19:02", "nick": "u1", "message": "the wallet handling is clean"},
        {"time": "19:02", "nick": "u2", "message": "the network code is solid"},
        {"time": "19:03", "nick": "u3", "message": "wallet keys look safe"},
        {"time": "19:03", "nick": "u4", "message": "network propagation seems fast"},
        {"time": "19:04", "nick": "u5", "message": "wallet export is reasonable"},
        {"time": "19:04", "nick": "u6", "message": "network peers are fine"},
        {"time": "19:05", "nick": "u7", "message": "wallet descriptors match"},
        {"time": "19:06", "nick": "host", "message": "#endmeeting"},
    ]
    questions = [
        {"number": 1, "text": "What about the wallet design?"},
        {"number": 2, "text": "What about the network behavior?"},
    ]
    result = segment_irc_log(log, questions, host_nick="host")
    seg1 = result["segments"][1]
    seg2 = result["segments"][2]
    seg1_msgs = " ".join(e["message"] for e in seg1).lower()
    seg2_msgs = " ".join(e["message"] for e in seg2).lower()
    # Wallet-keyword entries land in Q1, network-keyword entries in Q2.
    assert "wallet handling" in seg1_msgs
    assert "wallet keys" in seg1_msgs
    assert "network code" in seg2_msgs
    assert "network propagation" in seg2_msgs
    # And critically they are NOT cross-contaminated.
    assert "network code" not in seg1_msgs
    assert "wallet keys" not in seg2_msgs
