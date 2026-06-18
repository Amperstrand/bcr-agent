"""Tests for scraper.py — HTML parsing functions (no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from scraper import strip_html, extract_diff_from_html, parse_workshop


# Synthetic workshop page exercising the regexes in parse_workshop.
SAMPLE_HTML = """
<html><body>
<h1>Wallet Export Workshop</h1>
<time datetime="2025-08-06">August 6, 2025</time>
<p style="font-weight:bold"><a href="https://github.com/bitcoin/bitcoin/pull/12345">bitcoin-core PR #12345</a></p>
Host: <a href="/users/ryanofsky">ryanofsky</a>
PR author: <a href="/users/achow101">achow101</a>

<h2 id="notes">Notes</h2>
<p>This PR adds an exportwatchonlywallet RPC.&nbsp;It is related to descriptors.</p>
<h2 id="questions">Questions</h2>
<h3 id="concept">Concept</h3>
<ul>
<li><p>What does the wallet export RPC do?</p></li>
<li><p>How are descriptors handled?</p></li>
</ul>
<h3 id="implementation">Implementation</h3>
<ul>
<li><p>Where is the new RPC registered?</p></li>
</ul>
<h2 id="meeting-log">Meeting Log</h2>
<table class="log-line"><tr><td><span class="log-time">19:00</span></td>
<td><span class="log-nick">&lt;ryanofsky&gt;</span></td>
<td><span class="log-msg">#startmeeting</span></td></tr></table>
<table class="log-line"><tr><td><span class="log-time">19:01</span></td>
<td><span class="log-nick">&lt;alice&gt;</span></td>
<td><span class="log-msg">The RPC looks &amp; works well</span></td></tr></table>
</body></html>
"""


def test_strip_html_removes_tags_and_entities():
    assert strip_html("<p>Hello &amp; world</p>") == "Hello & world"
    assert strip_html("a&nbsp;b&quot;c") == 'a b"c'
    assert strip_html("  multiple   spaces  ") == "multiple spaces"


def test_strip_html_strips_all_tags():
    assert strip_html("<div><span>nested</span></div>") == "nested"


def test_extract_diff_from_html_extracts_pre_content():
    html = "<pre>diff --git a/foo &lt;a&gt; b/foo</pre>"
    result = extract_diff_from_html(html)
    assert "diff --git" in result
    assert "<a>" in result  # &lt;a&gt; unescaped


def test_extract_diff_from_html_fallback_without_pre():
    result = extract_diff_from_html("foo &amp; bar")
    assert result == "foo & bar"


def test_parse_workshop_extracts_metadata():
    w = parse_workshop(SAMPLE_HTML)
    assert w["title"] == "Wallet Export Workshop"
    assert w["date"] == "August 6, 2025"
    assert w["pr_url"] == "https://github.com/bitcoin/bitcoin/pull/12345"
    assert w["host"] == "ryanofsky"
    assert w["author"] == "achow101"


def test_parse_workshop_extracts_notes():
    w = parse_workshop(SAMPLE_HTML)
    assert "exportwatchonlywallet" in w["notes"]
    assert "descriptors" in w["notes"]


def test_parse_workshop_extracts_questions_with_sections():
    w = parse_workshop(SAMPLE_HTML)
    assert len(w["questions"]) == 3
    # Sections are lowercased h3 headers.
    sections = {q["section"] for q in w["questions"]}
    assert sections == {"concept", "implementation"}
    # Questions are numbered sequentially starting at 1.
    assert [q["number"] for q in w["questions"]] == [1, 2, 3]
    assert w["questions"][0]["text"] == "What does the wallet export RPC do?"


def test_parse_workshop_extracts_meeting_log():
    w = parse_workshop(SAMPLE_HTML)
    assert len(w["log"]) == 2
    first = w["log"][0]
    assert first["time"] == "19:00"
    # nicks are unescaped from &lt;ryanofsky&gt; -> ryanofsky
    assert first["nick"] == "ryanofsky"
    assert first["message"] == "#startmeeting"
    # entities in messages are unescaped
    assert w["log"][1]["message"] == "The RPC looks & works well"


def test_parse_workshop_handles_missing_sections():
    w = parse_workshop("<html><h1>Just a title</h1></html>")
    assert w["title"] == "Just a title"
    assert w["questions"] == []
    assert w["log"] == []
    assert w["notes"] == ""
