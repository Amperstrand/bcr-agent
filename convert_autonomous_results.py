#!/usr/bin/env python3
"""
Convert autonomous agent's q1.md-q8.md files to comparator-compatible JSON.

The comparator (comparator.py) expects:
  results/{workshop_id}_agent_results.json

The autonomous agent produces:
  /workspace/results/q1.md through q8.md

This script bridges the gap.
"""
import json
import os
import re
import sys


def extract_answer_text(filepath):
    """Extract the substantive answer from a q*.md file.

    Strategy: Take the full file content, but strip the question quote
    (lines starting with '>') and the section headers. Return the
    analysis sections.
    """
    with open(filepath) as f:
        content = f.read()

    # Remove blockquote question quotes
    lines = [l for l in content.split('\n') if not l.strip().startswith('>')]

    # Join and clean up
    text = '\n'.join(lines).strip()

    # Try to extract from "## My Analysis" onward if present
    analysis_match = re.search(r'## (?:My )?Analysis', text, re.IGNORECASE)
    if analysis_match:
        text = text[analysis_match.start():]

    return text


def convert(results_dir, workshop_id):
    """Convert q*.md files to agent_results.json format."""
    answers = []

    # Also extract metadata from summary.md if available
    summary_path = os.path.join(results_dir, 'summary.md')
    metadata = {}
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = f.read()
        # Extract host, author, PR URL from summary if present
        for pattern, key in [
            (r'Host?:\s*(.+)', 'host'),
            (r'Author?:\s*(.+)', 'author'),
            (r'PR(?:\s+URL)?:\s*(https?://\S+)', 'pr_url'),
        ]:
            m = re.search(pattern, summary, re.IGNORECASE)
            if m:
                metadata[key] = m.group(1).strip()

    for i in range(1, 9):
        qpath = os.path.join(results_dir, f'q{i}.md')
        if os.path.exists(qpath):
            text = extract_answer_text(qpath)
            answers.append({
                "question": i,
                "text": text,
                "mode": "autonomous",
                "source": f"q{i}.md",
            })
        else:
            answers.append({
                "question": i,
                "text": "",
                "mode": "autonomous",
                "source": f"q{i}.md (missing)",
            })

    result = {
        "answers": answers,
        "total_questions": len(answers),
        "mode": "autonomous",
        "date": metadata.get('date', ''),
        "host": metadata.get('host', ''),
        "author": metadata.get('author', ''),
        "pr_url": metadata.get('pr_url', ''),
    }

    output_path = os.path.join(results_dir, f'{workshop_id}_agent_results.json')
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Converted {len(answers)} answers to {output_path}")
    return output_path


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <results_dir> <workshop_id>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
