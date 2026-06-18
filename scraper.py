#!/usr/bin/env python3
"""
Scraper for Bitcoin Core PR Review Club workshops.
Parses workshop pages into structured JSON with notes, questions, and IRC log.
"""

import json
import re
import os
import sys
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def fetch_page(url: str, output_path: str) -> dict:
    """Fetch a web page and return structured data."""
    if os.path.exists(output_path):
        print(f"  Using cached: {output_path}")
        with open(output_path) as f:
            return json.load(f)

    print(f"  Fetching: {url}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; BCR-Agent/1.0)"
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")

    data = {"data": {"html": html, "url": url}}
    with open(output_path, "w") as f:
        json.dump(data, f)

    return data


def strip_html(html: str) -> str:
    """Remove HTML tags and clean up whitespace."""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_diff_from_html(html: str) -> str:
    """Extract diff text from GitHub's HTML-wrapped diff."""
    # GitHub wraps diffs in <pre> tag
    pre_match = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL)
    if pre_match:
        text = pre_match.group(1)
        # Unescape HTML entities
        text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        return text
    # Fallback: just strip all tags
    text = html.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    text = strip_html(text)
    return text


def parse_workshop(html: str) -> dict:
    """Parse a workshop page HTML into structured data."""
    result = {
        "title": "",
        "pr_url": "",
        "host": "",
        "author": "",
        "date": "",
        "component": "",
        "notes": "",
        "questions": [],
        "log": []
    }

    # Extract title
    title_match = re.search(r'<h1>(.*?)</h1>', html)
    if title_match:
        result["title"] = strip_html(title_match.group(1))

    # Extract date
    date_match = re.search(r'<time[^>]*>(.*?)</time>', html, re.DOTALL)
    if date_match:
        result["date"] = strip_html(date_match.group(1)).strip()

    # Extract PR URL
    pr_match = re.search(r'<p style="font-weight:bold">\s*<a href="(https://github\.com/bitcoin/bitcoin/pull/\d+)"', html)
    if pr_match:
        result["pr_url"] = pr_match.group(1)

    # Extract host
    host_match = re.search(r'Host:\s*<a[^>]*>(\w+)</a>', html)
    if host_match:
        result["host"] = host_match.group(1)

    # Extract author
    author_match = re.search(r'PR author:\s*<a[^>]*>(\w+)</a>', html)
    if author_match:
        result["author"] = author_match.group(1)

    # Extract Notes section
    notes_match = re.search(
        r'<h2 id="notes">Notes</h2>(.*?)<h2 id="questions">Questions</h2>',
        html, re.DOTALL
    )
    if notes_match:
        result["notes"] = strip_html(notes_match.group(1))

    # Extract Questions section
    questions_match = re.search(
        r'<h2 id="questions">Questions</h2>(.*?)<h2 id="meeting-log">Meeting Log</h2>',
        html, re.DOTALL
    )
    if questions_match:
        questions_html = questions_match.group(1)

        # Find sub-sections (Concept, Implementation, etc.)
        # Split by h3 headers
        sections = re.split(r'<h3[^>]*>(.*?)</h3>', questions_html)

        current_section = "general"
        i = 0
        while i < len(sections):
            if i % 2 == 1:  # This is a section header
                current_section = strip_html(sections[i]).lower()
                i += 1
                continue

            # This is the content - extract list items
            content = sections[i]
            items = re.findall(r'<li>\s*<p>(.*?)</p>', content, re.DOTALL)
            if not items:
                items = re.findall(r'<li>(.*?)</li>', content, re.DOTALL)

            for idx, item in enumerate(items):
                q_text = strip_html(item)
                if q_text:
                    result["questions"].append({
                        "section": current_section,
                        "number": len(result["questions"]) + 1,
                        "text": q_text
                    })
            i += 1

    # Extract Meeting Log
    log_match = re.search(
        r'<h2 id="meeting-log">Meeting Log</h2>(.*?)$',
        html, re.DOTALL
    )
    if log_match:
        log_html = log_match.group(1)

        # Parse log entries using table-based approach
        # Each entry is in a <table class="log-line">
        log_tables = re.findall(
            r'<table class="log-line"[^>]*>(.*?)</table>',
            log_html, re.DOTALL
        )

        for table in log_tables:
            time_match = re.search(r'log-time">\s*(.*?)\s*</td>', table, re.DOTALL)
            nick_match = re.search(r'log-nick[^>]*>(.*?)</span>', table, re.DOTALL)
            msg_match = re.search(r'log-msg">(.*?)</span>', table, re.DOTALL)

            if time_match and nick_match and msg_match:
                time = re.sub(r'<[^>]+>', '', time_match.group(1)).strip()
                nick = re.sub(r'<[^>]+>', '', nick_match.group(1)).strip()
                # Nick is HTML-escaped: &lt;ryanofsky&gt; -> ryanofsky
                nick = nick.replace('&lt;', '').replace('&gt;', '').strip()
                msg = re.sub(r'<[^>]+>', '', msg_match.group(1)).strip()
                # Unescape HTML entities in message
                msg = msg.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                if msg:
                    result["log"].append({
                        "time": time,
                        "nick": nick,
                        "message": msg
                    })

    return result


def fetch_pr_diff(pr_number: int, output_dir: str) -> str:
    """Fetch the PR diff from GitHub."""
    diff_path = os.path.join(output_dir, f"pr_{pr_number}_diff.txt")

    if os.path.exists(diff_path):
        print(f"  Using cached diff: {diff_path}")
        with open(diff_path) as f:
            return f.read()

    # Use page_reader to fetch the .diff URL
    json_path = os.path.join(output_dir, f"pr_{pr_number}_diff.json")
    data = fetch_page(f"https://github.com/bitcoin/bitcoin/pull/{pr_number}.diff", json_path)

    html = data.get("data", {}).get("html", "")
    # Extract diff from GitHub's HTML wrapper
    text = extract_diff_from_html(html)

    with open(diff_path, "w") as f:
        f.write(text)

    return text


def scrape_workshop(workshop_id: str) -> dict:
    """Main entry: scrape a workshop and save structured data."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # Fetch the workshop page
    json_path = os.path.join(DATA_DIR, f"workshop_{workshop_id}.json")
    page_data = fetch_page(f"https://bitcoincore.reviews/{workshop_id}", json_path)

    html = page_data.get("data", {}).get("html", "")
    if not html:
        raise ValueError(f"No HTML content for workshop {workshop_id}")

    # Parse the workshop
    workshop = parse_workshop(html)

    # Extract PR number from URL
    pr_match = re.search(r'/pull/(\d+)', workshop.get("pr_url", ""))
    if pr_match:
        pr_number = int(pr_match.group(1))
        workshop["pr_number"] = pr_number

        # Fetch the PR diff
        try:
            diff = fetch_pr_diff(pr_number, DATA_DIR)
            workshop["pr_diff_truncated"] = diff[:50000]  # Cap at 50k chars
            workshop["pr_diff_lines"] = diff.count('\n')
        except Exception as e:
            print(f"  Warning: Could not fetch PR diff: {e}")
            workshop["pr_diff_truncated"] = ""
            workshop["pr_diff_lines"] = 0

    # Save structured data
    output_path = os.path.join(DATA_DIR, f"{workshop_id}_structured.json")
    with open(output_path, "w") as f:
        json.dump(workshop, f, indent=2)

    print(f"\n  Workshop: {workshop['title']}")
    print(f"  PR: {workshop.get('pr_url', 'N/A')}")
    print(f"  Questions: {len(workshop['questions'])}")
    print(f"  Log entries: {len(workshop['log'])}")
    print(f"  Notes length: {len(workshop['notes'])} chars")
    print(f"  PR diff: {workshop.get('pr_diff_lines', 0)} lines")
    print(f"  Saved to: {output_path}")

    return workshop


if __name__ == "__main__":
    workshop_id = sys.argv[1] if len(sys.argv) > 1 else "32489"
    workshop = scrape_workshop(workshop_id)
