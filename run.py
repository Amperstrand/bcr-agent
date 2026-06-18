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

    # Full pipeline with publishing (Nostr + Blossom):
    python run.py full <workshop_id> --publish --nsec-file /path/to/nsec

    # With Cashu payment (for files >1MB):
    python run.py full <workshop_id> --publish --nsec-file /path/to/nsec --cashu-token cashuB...

    # Publish only (pipeline already run, just upload + announce):
    python run.py publish <workshop_id> --nsec-file /path/to/nsec
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from scraper import scrape_workshop
from segmenter import process_workshop
from agent import run_agent
from comparator import run_comparator
from reporter import generate_report


RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def full_pipeline(workshop_id: str):
    """Run the full pipeline: scrape -> segment -> agent (both modes) -> compare -> report."""
    print("\n" + "=" * 60)
    print(f"FULL PIPELINE - Workshop: {workshop_id}")
    print("=" * 60 + "\n")

    print("\n[1/5] Scraping workshop...")
    scrape_workshop(workshop_id)

    print("\n[2/5] Segmenting IRC log + fetching GitHub comments...")
    process_workshop(workshop_id)

    print("\n[3/5] Running AI reviewer (blind mode)...")
    run_agent(workshop_id, mode="blind")

    print("\n[4/5] Running AI reviewer (augmented mode)...")
    run_agent(workshop_id, mode="augmented")

    print("\n[5/5] Generating reports...")
    generate_report(workshop_id, mode="blind")
    generate_report(workshop_id, mode="augmented")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print("\nResults in: bcr-agent/results/")
    print(f"  - {workshop_id}_blind_results.json      (blind mode answers)")
    print(f"  - {workshop_id}_augmented_results.json  (augmented mode answers)")
    print(f"  - {workshop_id}_blind_report.txt        (blind mode report)")
    print(f"  - {workshop_id}_augmented_report.txt    (augmented mode report)")


def _find_report(workshop_id: str) -> str:
    """Find the best report file to publish."""
    # Prefer augmented report, fall back to blind, then any report
    candidates = [
        os.path.join(RESULTS_DIR, f"{workshop_id}_augmented_report.txt"),
        os.path.join(RESULTS_DIR, f"{workshop_id}_blind_report.txt"),
        os.path.join(RESULTS_DIR, f"{workshop_id}_report.txt"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        f"No report found for workshop {workshop_id}. Run the pipeline first: python run.py full {workshop_id}"
    )


def _load_workshop_meta(workshop_id: str) -> dict:
    """Load workshop metadata from the structured JSON for richer Nostr events."""
    structured_path = os.path.join(DATA_DIR, f"{workshop_id}_structured.json")
    if os.path.exists(structured_path):
        with open(structured_path) as f:
            return json.load(f)
    return {}


def publish_results(
    workshop_id: str,
    nsec_file: str,
    cashu_token: str = None,
    blossom_server: str = "https://blossom.psbt.me",
    relays: list = None,
    archive_dir: str = None,
):
    """Upload the report to Blossom and publish NIP-90 Nostr events.

    This is the "we're done" announcement sequence:
    1. Upload report.txt to blossom.psbt.me (BUD-02 + Cashu if needed)
    2. Publish NIP-90 job result (kind 6500) with the report URL
    3. Publish human-visible text note (kind 1)
    """
    from blossom_publisher import upload_to_blossom
    from nostr_publisher import announce_completion, publish_processing_status

    report_path = _find_report(workshop_id)
    workshop_meta = _load_workshop_meta(workshop_id)

    print("\n" + "=" * 60)
    print("PUBLISHING RESULTS")
    print("=" * 60)

    # 1. Publish "processing" status
    print("\n[1/3] Publishing processing status to Nostr...")
    status_result = publish_processing_status(
        nsec_file=nsec_file,
        workshop_id=workshop_id,
        stage="Publishing results to Blossom",
        relays=relays,
    )
    print(f"  Status: {'OK' if status_result.get('success') else 'FAILED'}")

    # 2. Upload to Blossom
    print(f"\n[2/3] Uploading report to {blossom_server}...")
    upload_result = upload_to_blossom(
        file_path=report_path,
        nsec_file=nsec_file,
        server_url=blossom_server,
        cashu_token=cashu_token,
    )
    report_url = upload_result.get("url", f"{blossom_server}/{upload_result.get('sha256', '')}")
    print(f"  Report URL: {report_url}")

    # 3. Publish Nostr announcement
    print("\n[3/3] Publishing NIP-90 events to Nostr...")

    # Extract metrics from results
    metrics = {}
    for mode in ("blind", "augmented"):
        results_path = os.path.join(RESULTS_DIR, f"{workshop_id}_{mode}_results.json")
        if os.path.exists(results_path):
            with open(results_path) as f:
                results = json.load(f)
            metrics[f"{mode}_questions"] = results.get("questions_answered", 0)
            metrics[f"{mode}_total"] = results.get("total_questions", 0)

    announce_results = announce_completion(
        nsec_file=nsec_file,
        workshop_id=workshop_id,
        report_url=report_url,
        pr_title=workshop_meta.get("title", ""),
        pr_url=workshop_meta.get("pr_url", ""),
        metrics=metrics if metrics else None,
        relays=relays,
    )

    for r in announce_results:
        event_type = r.get("event", "unknown")
        success = r.get("success", False)
        event_id = r.get("event_id", "")
        print(f"  {event_type}: {'OK' if success else 'FAILED'} ({event_id[:16]}...)" )

    print("\n" + "=" * 60)
    print("PUBLISHING COMPLETE")
    print(f"  Report: {report_url}")
    print(f"  Nostr events published to {len(relays) if relays else 3} relays")
    print("=" * 60)

    if archive_dir:
        print(f"\n[4/4] Exporting artifacts to {archive_dir}...")
        from artifact_export import export_artifacts
        export_result = export_artifacts(
            workshop_id=workshop_id,
            source_dir=os.path.dirname(__file__),
            dest_dir=archive_dir,
            blossom_server=blossom_server,
        )
        if export_result["blocked"]:
            print(f"  ⚠ {len(export_result['blocked'])} files BLOCKED (contained secrets)")
        if export_result["redacted"]:
            print(f"  ⚠ {len(export_result['redacted'])} files REDACTED (secrets scrubbed)")
        print(f"  ✓ {len(export_result['clean'])} files exported safely")

    return {"report_url": report_url, "events": announce_results}

def main():
    parser = argparse.ArgumentParser(
        description="BCR Agent - Bitcoin Core PR Review Club AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Pipeline command")

    # Common workshop commands
    for cmd in ["scrape", "segment", "compare", "report"]:
        sp = subparsers.add_parser(cmd, help=f"Run {cmd}")
        sp.add_argument("workshop_id", help="Workshop ID (e.g. 32489)")
        sp.add_argument("mode", nargs="?", default="blind", choices=["blind", "augmented"])

    # Agent command
    sp = subparsers.add_parser("agent", help="Run the AI reviewer")
    sp.add_argument("workshop_id")
    sp.add_argument("mode", nargs="?", default="blind", choices=["blind", "augmented"])

    # Both command
    sp = subparsers.add_parser("both", help="Run both modes")
    sp.add_argument("workshop_id")

    # Full pipeline
    sp = subparsers.add_parser("full", help="Run full pipeline (scrape + segment + agent + compare + report)")
    sp.add_argument("workshop_id")
    sp.add_argument("--publish", action="store_true", help="Publish results to Blossom + Nostr after pipeline")
    sp.add_argument("--nsec-file", help="Path to Nostr private key file (for publishing)")
    sp.add_argument("--cashu-token", help="Cashu token for paid uploads (cashuB...)")
    sp.add_argument("--blossom-server", default="https://blossom.psbt.me")
    sp.add_argument("--relays", nargs="*", default=["wss://nos.lol", "wss://relay.damus.io", "wss://relay.primal.net"])
    sp.add_argument("--archive-dir", help="Directory to export artifacts (e.g., blossomfs mount)")

    # Publish command (standalone)
    sp = subparsers.add_parser("publish", help="Upload report + publish Nostr events (pipeline already run)")
    sp.add_argument("workshop_id")
    sp.add_argument("--nsec-file", required=True, help="Path to Nostr private key file")
    sp.add_argument("--cashu-token", help="Cashu token for paid uploads (cashuB...)")
    sp.add_argument("--blossom-server", default="https://blossom.psbt.me")
    sp.add_argument("--relays", nargs="*", default=["wss://nos.lol", "wss://relay.damus.io", "wss://relay.primal.net"])
    sp.add_argument("--archive-dir", help="Directory to export artifacts (e.g., blossomfs mount)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # --- Execute pipeline commands ---
    if args.command == "scrape":
        scrape_workshop(args.workshop_id)
    elif args.command == "segment":
        process_workshop(args.workshop_id)
    elif args.command == "agent":
        run_agent(args.workshop_id, mode=args.mode)
    elif args.command == "both":
        run_agent(args.workshop_id, mode="blind")
        run_agent(args.workshop_id, mode="augmented")
    elif args.command == "compare":
        run_comparator(args.workshop_id, mode=args.mode)
    elif args.command == "report":
        generate_report(args.workshop_id)
    elif args.command == "full":
        full_pipeline(args.workshop_id)

        if args.publish:
            if not args.nsec_file:
                print("\nError: --publish requires --nsec-file")
                sys.exit(1)
            publish_results(
                workshop_id=args.workshop_id,
                nsec_file=args.nsec_file,
                cashu_token=args.cashu_token,
                blossom_server=args.blossom_server,
                relays=args.relays,
                archive_dir=getattr(args, 'archive_dir', None),
            )
    elif args.command == "publish":
        publish_results(
            workshop_id=args.workshop_id,
            nsec_file=args.nsec_file,
            cashu_token=args.cashu_token,
            blossom_server=args.blossom_server,
            relays=args.relays,
            archive_dir=getattr(args, 'archive_dir', None),
        )


if __name__ == "__main__":
    main()
