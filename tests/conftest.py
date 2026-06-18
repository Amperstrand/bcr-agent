"""Shared pytest fixtures for BCR Agent tests.

These fixtures are synthetic but realistic: they mirror the shapes produced by
scraper.parse_workshop (IRC log entries, workshop questions) so segmenter and
comparator tests run deterministically without network or LLM calls.
"""
import pytest


@pytest.fixture
def sample_log():
    """A small IRC meeting log in the shape scraper.parse_workshop produces.

    ryanofsky hosts, starts the meeting, asks two numbered questions, then ends.
    alice and bob respond substantively to each.
    """
    return [
        {"time": "19:00", "nick": "ryanofsky", "message": "#startmeeting"},
        {"time": "19:00", "nick": "alice", "message": "#here"},
        {"time": "19:00", "nick": "bob", "message": "#here"},
        {"time": "19:00", "nick": "corebot", "message": "Logged at https://example.org/log"},
        {"time": "19:01", "nick": "ryanofsky", "message": "Welcome to the PR review club"},
        {"time": "19:02", "nick": "ryanofsky",
         "message": "1. Did you review the wallet export changes? What did you think?"},
        {"time": "19:03", "nick": "alice",
         "message": "Yes, the exportwatchonlywallet RPC looks reasonable to me"},
        {"time": "19:04", "nick": "bob",
         "message": "I had concerns about the descriptor handling in the export path"},
        {"time": "19:05", "nick": "ryanofsky",
         "message": "2. How does the new RPC interact with the keypool?"},
        {"time": "19:06", "nick": "alice",
         "message": "The keypool is not affected directly by this export"},
        {"time": "19:07", "nick": "bob",
         "message": "Right, the watch-only addresses are kept separate from the keypool"},
        {"time": "19:08", "nick": "ryanofsky", "message": "#endmeeting"},
    ]


@pytest.fixture
def sample_questions():
    return [
        {"number": 1, "section": "concept",
         "text": "Did you review the wallet export changes? What did you think?"},
        {"number": 2, "section": "concept",
         "text": "How does the new RPC interact with the keypool?"},
    ]
