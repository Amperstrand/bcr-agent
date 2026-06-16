#!/usr/bin/env python3
"""
BCR Agent - CLI runner for the Bitcoin Core PR Review Club AI Agent.

Usage:
    python run.py scrape <workshop_id>              # Scrape a workshop
    python run.py segment <workshop_id>             # Segment IRC log + fetch GitHub comments
    python run.py agent <workshop_id> [mode]        # Run the AI reviewer (mode: blind|augmented)
    python run.py both <workshop_id>                # Run both modes and compare
    python run.py compare <workshop_id> [mode]      # Compare vs IRC log
    python run.py report <workshop_id> [mode]       # Generate report
    python run.py full <workshop_id>                # Run full pipeline (blind + augmented)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from scraper import scrape_workshop
from segmenter import process_workshop
from agent import run_agent
from comparator import run_comparator
from reporter import generate_report


def full_pipeline(workshop_id: str):
    """Run the full pipeline: scrape → segment → agent (both modes) → compare → report."""
    print("\n" + "=" * 60)
    print(f"FULL PIPELINE — Workshop: {workshop_id}")
    print("=" * 60 + "\n")

    print("\n[1/5] Scraping workshop...")
    scrape_workshop(workshop_id)

    print("\n[2/5] Segmenting IRC log + fetching GitHub comments...")
    process_workshop(workshop_id)

    print("\n[3/5] Running AI reviewer (blind mode)...")
    blind_results = run_agent(workshop_id, mode="blind")

    print("\n[4/5] Running AI reviewer (augmented mode)...")
    aug_results = run_agent(workshop_id, mode="augmented")

    print("\n[5/5] Generating reports...")
    generate_report(workshop_id, mode="blind")
    generate_report(workshop_id, mode="augmented")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"\nResults in: bcr-agent/results/")
    print(f"  - {workshop_id}_blind_results.json      (blind mode answers)")
    print(f"  - {workshop_id}_augmented_results.json  (augmented mode answers)")
    print(f"  - {workshop_id}_blind_report.txt        (blind mode report)")
    print(f"  - {workshop_id}_augmented_report.txt    (augmented mode report)")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    workshop_id = sys.argv[2]

    if command == "scrape":
        scrape_workshop(workshop_id)
    elif command == "segment":
        process_workshop(workshop_id)
    elif command == "agent":
        mode = sys.argv[3] if len(sys.argv) > 3 else "blind"
        run_agent(workshop_id, mode=mode)
    elif command == "both":
        run_agent(workshop_id, mode="blind")
        run_agent(workshop_id, mode="augmented")
    elif command == "compare":
        mode = sys.argv[3] if len(sys.argv) > 3 else "blind"
        run_comparator(workshop_id, mode=mode)
    elif command == "report":
        mode = sys.argv[3] if len(sys.argv) > 3 else "blind"
        generate_report(workshop_id, mode=mode)
    elif command == "full":
        full_pipeline(workshop_id)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
