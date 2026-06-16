#!/usr/bin/env python3
"""
BCR Segment Matcher - Maps IRC log entries to specific workshop questions.

Strategy:
1. Find "anchor" messages where the host explicitly asks a question
2. Everything between two anchors belongs to the earlier question
3. Handle: un-numbered first question, questions posted together, cross-topic drift

Also extracts GitHub PR review comments for augmented mode.
"""

import json
import re
import os
import subprocess

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Reuse config from agent.py
import sys
sys.path.insert(0, os.path.dirname(__file__))
from agent import get_llm_cli_path


def strip_html(html: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching: lowercase, remove extra whitespace, strip punctuation."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fingerprint(text: str, length: int = 50) -> str:
    """Create a normalized fingerprint of text for matching."""
    return normalize_text(text)[:length]


def detect_host(log: list) -> str:
    """Auto-detect the host nick from the log."""
    # The first person to say #startmeeting is usually the host
    for entry in log:
        if "#startmeeting" in entry["message"]:
            return entry["nick"]
    # Fallback: the most frequent speaker who asks questions
    return None


def find_question_anchors(log: list, questions: list, host_nick: str) -> list:
    """Find where each question is introduced in the IRC log.
    
    Returns list of (log_index, question_number) tuples, sorted by log_index.
    """
    question_map = {q["number"]: q["text"] for q in questions}
    anchors = []  # (log_index, question_number)
    matched_questions = set()
    
    for i, entry in enumerate(log):
        msg = entry["message"]
        nick = entry["nick"]
        
        if nick != host_nick:
            continue
        
        # --- Pattern 1: Explicit numbered question ---
        # "1. Did you review..." or "Next up is 2. Why..."
        # Also handles: "7. In wallet_exported_watchonly.py..."
        numbered_matches = re.finditer(
            r'(?:^|\s)(\d+)\.\s+([A-Z\[({]|Did|Why|How|What|Where|When|Can|Should|Is|Prior|Consider|In |For |Explain|Compare)',
            msg
        )
        for m in numbered_matches:
            q_num = int(m.group(1))
            if q_num in question_map and q_num not in matched_questions:
                anchors.append((i, q_num))
                matched_questions.add(q_num)
        
        # --- Pattern 2: "First question" / "Next question" ---
        if not any(qn in matched_questions for qn in [1]) and re.search(r'first question', msg.lower()):
            if 1 in question_map and 1 not in matched_questions:
                anchors.append((i, 1))
                matched_questions.add(1)
        
        # --- Pattern 3: Host says question text verbatim ---
        # For questions not yet matched, check if the message contains the question text
        for q_num, q_text in question_map.items():
            if q_num in matched_questions:
                continue
            
            # Use different fingerprint lengths for different match strictness
            q_fp = fingerprint(q_text, 60)
            msg_fp = fingerprint(msg, len(msg))
            
            if len(q_fp) > 15 and q_fp in msg_fp:
                anchors.append((i, q_num))
                matched_questions.add(q_num)
                break  # One match per message
    
    # Sort by log index
    anchors.sort(key=lambda x: x[0])
    
    # Deduplicate: if same question appears twice at adjacent indices, keep first
    deduped = []
    for anchor in anchors:
        if deduped and deduped[-1][1] == anchor[1]:
            continue  # Skip duplicate
        deduped.append(anchor)
    anchors = deduped
    
    return anchors


def segment_irc_log(log: list, questions: list, host_nick: str = None) -> dict:
    """Segment the IRC log into per-question chunks.
    
    Returns:
        segments: dict mapping question_number -> list of IRC entries
        anchors: list of (log_index, question_number)
        host_nick: detected or provided host nick
        unanchored: list of question numbers not found in log
    """
    if not host_nick:
        host_nick = detect_host(log)
    
    anchors = find_question_anchors(log, questions, host_nick)
    matched_questions = {a[1] for a in anchors}
    
    # Build segments: each segment runs from anchor to next anchor (or end)
    segments = {}
    
    for j, (anchor_idx, q_num) in enumerate(anchors):
        # Find end: next anchor or end of log
        if j + 1 < len(anchors):
            end_idx = anchors[j + 1][0]
        else:
            end_idx = len(log)
        
        segments[q_num] = log[anchor_idx:end_idx]
    
    # Handle unanchored questions
    # Sometimes the host posts multiple questions in a single message
    # Check if any anchor message contains text from multiple questions
    unanchored = [q["number"] for q in questions if q["number"] not in matched_questions]
    
    for q_num in unanchored:
        q_text = questions[q_num - 1]["text"]  # Assuming 1-indexed
        
        # Strategy: find the closest anchor before where this question would logically go
        # The question belongs between its neighbors in sequence
        prev_anchored = None
        next_anchored = None
        for q in questions:
            if q["number"] < q_num and q["number"] in matched_questions:
                prev_anchored = q["number"]
            if q["number"] > q_num and q["number"] in matched_questions and next_anchored is None:
                next_anchored = q["number"]
        
        if prev_anchored and prev_anchored in segments:
            # Split the previous segment: look for where discussion shifts to this question
            prev_segment = segments[prev_anchored]
            
            # Try to find the question text in the segment
            found = False
            for k, entry in enumerate(prev_segment):
                if fingerprint(q_text, 40) in fingerprint(entry["message"], len(entry["message"])):
                    # Split here
                    segments[q_num] = prev_segment[k:]
                    segments[prev_anchored] = prev_segment[:k]
                    found = True
                    break
            
            if not found:
                # Can't find exact split point - assign empty segment
                segments[q_num] = []
        else:
            segments[q_num] = []
    
    # Special handling for questions posted together (e.g., "7. ... 8. ...")
    # When two adjacent questions have very unequal segments, merge and re-split
    # by topic relevance (keyword matching)
    _rebalance_interleaved(segments, questions, log, host_nick)
    
    return {
        "segments": segments,
        "anchors": [{"log_index": idx, "question_number": qnum} for idx, qnum in anchors],
        "host_nick": host_nick,
        "unanchored_questions": [q for q in unanchored],
    }


def _rebalance_interleaved(segments: dict, questions: list, log: list, host_nick: str):
    """Rebalance segments when questions were posted together and discussion is interleaved.
    
    Detects when a question has a very small segment (< 3 substantive entries) 
    while the next question has a large segment. This happens when the host posts
    multiple questions at once ("feel free to respond to either").
    
    In this case, merge both segments and re-assign each entry to the question
    it's most relevant to (by keyword matching). Entries that match neither
    question specifically go to both (shared context).
    """
    question_map = {q["number"]: q["text"] for q in questions}
    q_nums = sorted([k for k in segments.keys() if isinstance(k, int)])
    
    for idx in range(len(q_nums) - 1):
        q_a = q_nums[idx]
        q_b = q_nums[idx + 1]
        
        seg_a_subst = get_substantive_entries(segments[q_a])
        seg_b_subst = get_substantive_entries(segments[q_b])
        
        # If Q_a has very few entries and Q_b has many, they were probably posted together
        if len(seg_a_subst) < 3 and len(seg_b_subst) > 5:
            # Merge both segments
            merged = segments[q_a] + segments[q_b]
            
            # Build keyword sets for each question
            keywords_a = _extract_keywords(question_map.get(q_a, ""))
            keywords_b = _extract_keywords(question_map.get(q_b, ""))
            
            # Also add contextual keywords from the host's summary answer
            # Look for the host explicitly referencing question numbers
            entries_a = []
            entries_b = []
            entries_shared = []
            
            for entry in merged:
                nick = entry["nick"]
                msg_lower = entry["message"].lower()
                
                # Check for explicit question references
                explicit_a = bool(re.search(rf'(?:question|q)\s*{q_a}\b', msg_lower))
                explicit_b = bool(re.search(rf'(?:question|q)\s*{q_b}\b', msg_lower))
                
                # Check for "the last one" / "on the last" references
                # These typically refer to the higher-numbered question
                refers_to_last = any(phrase in msg_lower for phrase in [
                    "the last one", "on the last", "for the last",
                    "the last question", "the final one",
                ])
                
                # Score relevance to each question
                score_a = sum(1 for kw in keywords_a if kw in msg_lower)
                score_b = sum(1 for kw in keywords_b if kw in msg_lower)
                
                if explicit_a:
                    entries_a.append(entry)
                elif explicit_b or refers_to_last:
                    entries_b.append(entry)
                elif score_a > score_b and score_a >= 2:
                    entries_a.append(entry)
                elif score_b > score_a and score_b >= 2:
                    entries_b.append(entry)
                elif score_a > 0 and score_b == 0:
                    entries_a.append(entry)
                elif score_b > 0 and score_a == 0:
                    entries_b.append(entry)
                else:
                    # Shared or unclear — put in both
                    entries_shared.append(entry)
            
            # Assign shared entries to both segments
            segments[q_a] = entries_a + entries_shared
            segments[q_b] = entries_b + entries_shared


def _extract_keywords(text: str) -> set:
    """Extract meaningful keywords from question text for relevance matching."""
    # Remove common stop words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "must", "ought",
        "what", "which", "who", "whom", "whose", "where", "when", "how", "why",
        "that", "this", "these", "those", "it", "its", "they", "them", "their",
        "and", "but", "or", "nor", "not", "no", "so", "if", "then", "than",
        "too", "very", "just", "about", "above", "after", "before", "between",
        "each", "few", "more", "most", "other", "some", "such", "only", "also",
        "into", "over", "with", "from", "for", "you", "your", "there", "here",
    }
    
    words = set()
    for word in text.lower().split():
        # Clean word
        word = re.sub(r'[^\w]', '', word)
        if len(word) > 3 and word not in stop_words:
            words.add(word)
    
    # Also add compound terms (bigrams)
    text_lower = text.lower()
    compound_terms = [
        "watch-only", "watchonly", "watch_only",
        "keypoolrefill", "keypool", "key pool",
        "descriptor", "cache", "hardened",
        "dumpwallet", "importwallet", "importdescriptors",
        "exportwatchonlywallet", "export",
        "avoid_reuse", "avoidreuse",
        "offline", "online", "signing",
        "spendability", "rescan",
    ]
    for term in compound_terms:
        if term in text_lower:
            words.add(term)
    
    return words


def format_segment(segment: list) -> str:
    """Format an IRC segment as readable text."""
    lines = []
    for entry in segment:
        lines.append(f"[{entry['time']}] {entry['nick']}: {entry['message']}")
    return "\n".join(lines)


def get_substantive_entries(segment: list) -> list:
    """Filter out bot messages and trivial greetings."""
    substantive = []
    for entry in segment:
        nick = entry["nick"]
        msg = entry["message"]
        if nick in ("corebot", "corebot`"):
            continue
        if len(msg) < 5 and msg.lower().strip() in ("hi", "hey", "hello", "hola", "+1"):
            continue
        if msg.startswith(("#startmeeting", "#endmeeting", "#here", "#topic")):
            continue
        substantive.append(entry)
    return substantive


def fetch_github_comments(pr_number: int, output_dir: str) -> list:
    """Fetch PR review comments from GitHub."""
    comments = []
    pr_json_path = os.path.join(output_dir, f"pr_{pr_number}_comments.json")
    
    if not os.path.exists(pr_json_path):
        try:
            print(f"  Fetching GitHub PR page for #{pr_number}...")
            result = subprocess.run(
                [get_llm_cli_path(), "function", "-n", "page_reader", 
                 "-a", json.dumps({"url": f"https://github.com/bitcoin/bitcoin/pull/{pr_number}"}),
                 "-o", pr_json_path],
                capture_output=True, text=True, timeout=60
            )
        except Exception as e:
            print(f"  Warning: Could not fetch PR page: {e}")
            return comments
    
    if os.path.exists(pr_json_path):
        try:
            with open(pr_json_path) as f:
                data = json.load(f)
            
            html = data.get("data", {}).get("html", "")
            
            # Extract comment bodies from GitHub's HTML
            comment_bodies = re.findall(
                r'<td[^>]*comment-body[^>]*>(.*?)</td>',
                html, re.DOTALL
            )
            
            for body in comment_bodies:
                text = strip_html(body)
                if len(text) > 20:
                    comments.append({
                        "type": "issue_comment",
                        "body": text[:5000],
                    })
            
            print(f"  Extracted {len(comments)} issue comments from PR page")
        except Exception as e:
            print(f"  Warning: Could not parse PR comments: {e}")
    
    return comments


def build_augmented_context(
    workshop: dict,
    segmentation: dict,
    question_number: int,
    github_comments: list = None,
    max_irc_chars: int = 6000,
    max_github_chars: int = 4000,
) -> str:
    """Build augmented context for a specific question (IRC + GitHub comments)."""
    parts = []
    
    # IRC discussion for this question
    segment = segmentation.get("segments", {}).get(str(question_number), [])
    if not segment:
        segment = segmentation.get("segments", {}).get(question_number, [])
    
    substantive = get_substantive_entries(segment)
    
    if substantive:
        irc_text = format_segment(substantive)
        if len(irc_text) > max_irc_chars:
            irc_text = irc_text[:max_irc_chars] + "\n... (truncated)"
        parts.append("## IRC Discussion (Human Reviewers)")
        parts.append("This is what human reviewers discussed when this question was asked in the live session.")
        parts.append("")
        parts.append(irc_text)
        parts.append("")
    
    # GitHub PR comments
    if github_comments:
        question = None
        for q in workshop["questions"]:
            if q["number"] == question_number:
                question = q
                break
        
        if question:
            q_keywords = set()
            for word in question["text"].split():
                if len(word) > 4:
                    q_keywords.add(word.lower())
            
            relevant_comments = []
            total_len = 0
            for comment in github_comments:
                body_lower = comment["body"].lower()
                relevance = sum(1 for kw in q_keywords if kw in body_lower)
                if relevance >= 2:
                    comment_text = comment["body"]
                    if total_len + len(comment_text) > max_github_chars:
                        remaining = max_github_chars - total_len
                        if remaining > 200:
                            relevant_comments.append(comment_text[:remaining] + "\n... (truncated)")
                        break
                    relevant_comments.append(comment_text)
                    total_len += len(comment_text)
            
            if relevant_comments:
                parts.append("## GitHub PR Comments (Relevant to This Question)")
                for i, comment in enumerate(relevant_comments):
                    parts.append(f"### Comment {i+1}")
                    parts.append(comment)
                    parts.append("")
    
    return "\n".join(parts)


def process_workshop(workshop_id: str) -> tuple:
    """Full processing: segment IRC log + fetch GitHub comments."""
    data_path = os.path.join(DATA_DIR, f"{workshop_id}_structured.json")
    with open(data_path) as f:
        workshop = json.load(f)
    
    log = workshop["log"]
    questions = workshop["questions"]
    host_nick = detect_host(log)
    
    print(f"\nProcessing workshop: {workshop['title']}")
    print(f"Host: {host_nick}")
    print(f"Questions: {len(questions)}")
    print(f"Log entries: {len(log)}")
    
    # Segment the IRC log
    print("\nSegmenting IRC log...")
    segmentation = segment_irc_log(log, questions, host_nick)
    
    print(f"\nAnchors found:")
    for anchor in segmentation["anchors"]:
        q_num = anchor["question_number"]
        segment = segmentation["segments"].get(q_num, [])
        substantive = get_substantive_entries(segment)
        print(f"  Q{q_num} @ log[{anchor['log_index']}]: {len(segment)} entries ({len(substantive)} substantive)")
    
    if segmentation["unanchored_questions"]:
        print(f"\nUnanchored questions (auto-assigned): {segmentation['unanchored_questions']}")
    
    # Print per-question summary
    print(f"\nPer-question segments:")
    for q in questions:
        segment = segmentation["segments"].get(q["number"], [])
        substantive = get_substantive_entries(segment)
        print(f"  Q{q['number']}: {len(substantive)} substantive entries — {q['text'][:60]}...")
    
    # Fetch GitHub comments
    pr_number = workshop.get("pr_number")
    github_comments = []
    if pr_number:
        github_comments = fetch_github_comments(pr_number, DATA_DIR)
    
    # Save segmentation data
    serializable_segments = {}
    for q_num, segment in segmentation["segments"].items():
        serializable_segments[str(q_num)] = segment
    
    full_seg_path = os.path.join(DATA_DIR, f"{workshop_id}_segmentation.json")
    with open(full_seg_path, "w") as f:
        json.dump({
            "workshop_id": workshop_id,
            "host_nick": host_nick,
            "anchors": segmentation["anchors"],
            "unanchored_questions": segmentation["unanchored_questions"],
            "segments": serializable_segments,
        }, f, indent=2)
    
    print(f"\nSegmentation saved to: {full_seg_path}")
    
    if github_comments:
        comments_path = os.path.join(DATA_DIR, f"{workshop_id}_github_comments.json")
        with open(comments_path, "w") as f:
            json.dump(github_comments, f, indent=2)
        print(f"GitHub comments saved to: {comments_path}")
    
    return segmentation, github_comments


if __name__ == "__main__":
    import sys
    workshop_id = sys.argv[1] if len(sys.argv) > 1 else "32489"
    process_workshop(workshop_id)
