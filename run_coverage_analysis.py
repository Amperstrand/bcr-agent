#!/usr/bin/env python3
"""
Run coverage analysis: compare autonomous agent answers against IRC discussion.

Runs on the VM after the agent session. Sets up data paths, runs the comparator
and reporter, and saves the coverage report to the results directory.

Usage:
    python3 run_coverage_analysis.py <workshop_id>

Requires: workshop.json at /workspace/workshop.json
Produces: coverage_report.md and coverage_comparison.json in /workspace/results/
"""
import json
import os
import re
import shutil
import subprocess
import sys

BCR_DIR = "/opt/bcr-agent"
WORKSPACE = "/workspace"
RESULTS_DIR = f"{WORKSPACE}/results"
WORKSHOP_JSON = f"{WORKSPACE}/workshop.json"

sys.path.insert(0, BCR_DIR)


def setup_data_paths(workshop_id):
    """Create the data/ and results/ directories the comparator expects."""
    data_dir = os.path.join(BCR_DIR, "data")
    bcr_results = os.path.join(BCR_DIR, "results")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(bcr_results, exist_ok=True)

    structured_path = os.path.join(data_dir, f"{workshop_id}_structured.json")
    shutil.copy2(WORKSHOP_JSON, structured_path)
    print(f"  Copied workshop.json → {structured_path}")

    return data_dir, bcr_results


def convert_answers(workshop_id, bcr_results):
    """Convert q*.md files to the JSON format comparator expects."""
    from convert_autonomous_results import convert
    convert(RESULTS_DIR, workshop_id)

    src = os.path.join(RESULTS_DIR, f"{workshop_id}_agent_results.json")
    dst = os.path.join(bcr_results, f"{workshop_id}_agent_results.json")
    shutil.copy2(src, dst)
    print(f"  Converted q*.md → {dst}")


def run_comparison(workshop_id):
    """Run the comparator and reporter."""
    from comparator import run_comparator
    from reporter import generate_report

    print("  Running comparator (8 LLM calls, ~2-3 min)...")
    comp_data = run_comparator(workshop_id)

    comp_path = os.path.join(RESULTS_DIR, f"{workshop_id}_coverage_comparison.json")
    with open(comp_path, "w") as f:
        json.dump(comp_data, f, indent=2)
    print(f"  Comparison saved: {comp_path}")

    try:
        report_text = generate_report(workshop_id, mode="autonomous")
        report_path = os.path.join(RESULTS_DIR, "coverage_report.md")
        with open(report_path, "w") as f:
            f.write(report_text)
        print(f"  Report saved: {report_path}")
    except Exception as e:
        print(f"  Report generation failed: {e}")
        report_path = None

    return comp_path, report_path


def extract_coverage_summary(workshop_id):
    """Extract key metrics from the comparison for the Nostr event."""
    comp_path = os.path.join(RESULTS_DIR, f"{workshop_id}_coverage_comparison.json")
    if not os.path.exists(comp_path):
        return {}

    with open(comp_path) as f:
        data = json.load(f)

    total_q = len(data.get("comparisons", []))
    ratings = []
    for c in data.get("comparisons", []):
        text = c.get("comparison", "")
        m = re.search(r"(\d)/5", text)
        if m:
            ratings.append(int(m.group(1)))

    avg_rating = sum(ratings) / len(ratings) if ratings else 0
    return {
        "coverage_questions": total_q,
        "avg_quality_rating": f"{avg_rating:.1f}/5" if ratings else "N/A",
    }


def capture_stats():
    """Capture opencode stats as JSON."""
    try:
        result = subprocess.run(
            ["opencode", "stats"],
            capture_output=True, text=True, timeout=30
        )
        stats_path = os.path.join(RESULTS_DIR, "opencode_stats.txt")
        with open(stats_path, "w") as f:
            f.write(result.stdout)
        print(f"  Stats saved: {stats_path}")
        return stats_path
    except Exception as e:
        print(f"  Stats capture failed: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_coverage_analysis.py <workshop_id>")
        sys.exit(1)

    workshop_id = sys.argv[1]

    if not os.path.exists(WORKSHOP_JSON):
        print(f"ERROR: {WORKSHOP_JSON} not found")
        sys.exit(1)

    print("=" * 60)
    print("COVERAGE ANALYSIS")
    print("=" * 60)

    print("\n[1/4] Setting up data paths...")
    setup_data_paths(workshop_id)

    print("\n[2/4] Converting agent answers...")
    convert_answers(workshop_id, os.path.join(BCR_DIR, "results"))

    print("\n[3/4] Capturing opencode stats...")
    capture_stats()

    print("\n[4/4] Running comparator (this takes ~2-3 min)...")
    try:
        comp_path, report_path = run_comparison(workshop_id)
        summary = extract_coverage_summary(workshop_id)
        print(f"\n  Coverage: {summary}")
        print("\n✓ Coverage analysis complete")
    except Exception as e:
        print(f"\n✗ Coverage analysis failed: {e}")
        print("  Results still published without coverage data")


if __name__ == "__main__":
    main()
