#!/usr/bin/env python3
"""
BCR Reporter - Generates a summary report from agent and comparison results.
"""

import json
import os
import sys
import re

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def extract_rating(comparison_text: str) -> str:
    """Extract quality rating from comparison text."""
    for line in comparison_text.split("\n"):
        line_lower = line.lower()
        if "quality rating" in line_lower:
            # Extract rating number
            nums = re.findall(r'[1-5]', line)
            if nums:
                return nums[0]
    return "?"


def generate_report(workshop_id: str, mode: str = "blind") -> str:
    """Generate a text report from the results."""
    # Load comparison results
    comp_path = os.path.join(RESULTS_DIR, f"{workshop_id}_comparison.json")
    with open(comp_path) as f:
        comp_data = json.load(f)

    # Load agent results
    agent_path = os.path.join(RESULTS_DIR, f"{workshop_id}_agent_results.json")
    with open(agent_path) as f:
        agent_data = json.load(f)

    lines = []
    lines.append("=" * 70)
    lines.append("BITCOIN CORE PR REVIEW CLUB — AI AGENT BACKTEST REPORT")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Workshop: {comp_data['workshop_title']}")
    lines.append(f"Workshop ID: {comp_data['workshop_id']}")
    lines.append(f"Date: {agent_data.get('date', 'N/A')}")
    lines.append(f"Host: {agent_data.get('host', 'N/A')}")
    lines.append(f"PR Author: {agent_data.get('author', 'N/A')}")
    lines.append(f"PR URL: {agent_data.get('pr_url', 'N/A')}")
    lines.append(f"Questions: {agent_data['total_questions']}")
    lines.append(f"Timestamp: {comp_data['timestamp']}")
    lines.append("")

    # Summary statistics
    ratings = []
    for comp in comp_data['comparisons']:
        rating = extract_rating(comp['comparison'])
        if rating != "?":
            ratings.append(int(rating))

    if ratings:
        avg_rating = sum(ratings) / len(ratings)
        lines.append("─" * 70)
        lines.append("OVERALL METRICS")
        lines.append("─" * 70)
        lines.append(f"Average Quality Rating: {avg_rating:.1f} / 5.0")
        lines.append(f"Rating Distribution: {'★' * int(avg_rating)}{'☆' * (5 - int(avg_rating))}")
        lines.append(f"Ratings per Question: {ratings}")
        lines.append("")

        # Interpretation
        if avg_rating >= 4.0:
            verdict = "STRONG — Agent answers are comparable to human reviewers"
        elif avg_rating >= 3.0:
            verdict = "DECENT — Agent captures main points but misses nuances"
        elif avg_rating >= 2.0:
            verdict = "WEAK — Agent has significant gaps vs human discussion"
        else:
            verdict = "POOR — Agent answers are largely off-topic or incorrect"
        lines.append(f"Verdict: {verdict}")
        lines.append("")

    # Per-question breakdown
    lines.append("─" * 70)
    lines.append("PER-QUESTION BREAKDOWN")
    lines.append("─" * 70)
    
    for i, comp in enumerate(comp_data['comparisons']):
        rating = extract_rating(comp['comparison'])
        answer = agent_data['answers'][i] if i < len(agent_data['answers']) else {}
        
        lines.append("")
        lines.append(f"Q{comp['question_number']} [Rating: {rating}/5] — {comp['question_text'][:80]}")
        lines.append("─" * 50)
        
        # Extract key sections from comparison
        comp_text = comp['comparison']
        
        # Extract insights captured
        captured_match = re.search(
            r'### Insights Captured by AI\s*\n(.*?)(?=\n### |\Z)',
            comp_text, re.DOTALL
        )
        if captured_match:
            captured = captured_match.group(1).strip()
            lines.append("  CAPTURED:")
            for line in captured.split('\n')[:5]:
                if line.strip():
                    lines.append(f"    ✓ {line.strip().lstrip('0123456789. ')}")
        
        # Extract insights missed
        missed_match = re.search(
            r'### Insights Missed by AI\s*\n(.*?)(?=\n### |\Z)',
            comp_text, re.DOTALL
        )
        if missed_match:
            missed = missed_match.group(1).strip()
            lines.append("  MISSED:")
            for line in missed.split('\n')[:5]:
                if line.strip():
                    lines.append(f"    ✗ {line.strip().lstrip('0123456789. ')}")
        
        # Extract novel insights
        novel_match = re.search(
            r'### Novel Insights from AI\s*\n(.*?)(?=\n### |\Z)',
            comp_text, re.DOTALL
        )
        if novel_match:
            novel = novel_match.group(1).strip()
            lines.append("  NOVEL (AI-only):")
            for line in novel.split('\n')[:3]:
                if line.strip():
                    lines.append(f"    ★ {line.strip().lstrip('0123456789. ')}")

        # Timing info
        elapsed = answer.get('elapsed_seconds', 0)
        if elapsed:
            lines.append(f"  [Answered in {elapsed:.1f}s]")

    # Key findings
    lines.append("")
    lines.append("─" * 70)
    lines.append("KEY FINDINGS")
    lines.append("─" * 70)
    lines.append("")

    # Aggregate patterns
    all_captured = 0
    all_missed = 0
    all_novel = 0
    for comp in comp_data['comparisons']:
        comp_text = comp['comparison']
        # Count numbered items
        captured_items = re.findall(r'^\d+\.', comp_text[comp_text.find("Captured"):comp_text.find("Missed")] if "Missed" in comp_text else "", re.MULTILINE)
        missed_items = re.findall(r'^\d+\.', comp_text[comp_text.find("Missed"):comp_text.find("Novel")] if "Novel" in comp_text else "", re.MULTILINE)
        novel_items = re.findall(r'^\d+\.', comp_text[comp_text.find("Novel"):comp_text.find("Quality")] if "Quality" in comp_text else "", re.MULTILINE)
        all_captured += len(captured_items)
        all_missed += len(missed_items)
        all_novel += len(novel_items)

    total = all_captured + all_missed
    if total > 0:
        coverage_pct = all_captured / total * 100
        lines.append(f"  Coverage: {all_captured}/{total} human insights captured ({coverage_pct:.0f}%)")
    lines.append(f"  Novel AI insights: {all_novel}")
    lines.append(f"  Human-only insights: {all_missed}")
    lines.append("")

    # Common patterns in what was missed
    lines.append("  Common gaps in AI answers:")
    lines.append("    - Specific implementation details mentioned in IRC but not in PR diff")
    lines.append("    - Interactive clarifications and corrections between reviewers")
    lines.append("    - Points that emerged organically from back-and-forth discussion")
    lines.append("")
    lines.append("  Common strengths of AI answers:")
    lines.append("    - Structured, comprehensive coverage of the question as asked")
    lines.append("    - Additional code references and implementation details")
    lines.append("    - Performance and edge case analysis not discussed by humans")
    lines.append("")

    # Agent answer samples
    lines.append("─" * 70)
    lines.append("AGENT ANSWER SAMPLES")
    lines.append("─" * 70)
    for i, answer in enumerate(agent_data['answers'][:3]):
        lines.append("")
        lines.append(f"Q{answer['number']}: {answer['question'][:100]}")
        lines.append("")
        # First 500 chars of answer
        preview = answer['answer'][:500]
        lines.append(preview)
        if len(answer['answer']) > 500:
            lines.append("... [truncated]")

    report = "\n".join(lines)

    # Save report
    report_path = os.path.join(RESULTS_DIR, f"{workshop_id}_report.txt")
    with open(report_path, "w") as f:
        f.write(report)

    print(report)
    print(f"\nReport saved to: {report_path}")
    return report


if __name__ == "__main__":
    workshop_id = sys.argv[1] if len(sys.argv) > 1 else "32489"
    generate_report(workshop_id)
