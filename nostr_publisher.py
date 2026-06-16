#!/usr/bin/env python3
"""
BCR Agent — Nostr Publisher (NIP-90 DVM patterns)

Publishes Nostr events following the Data Vending Machine (NIP-90) protocol,
adapted from Origami74/dvm-cicd-runner patterns.

Event kinds used:
  - 31989: NIP-89 service announcement (one-time, for discoverability)
  - 7000:  Job feedback (status: processing, success, error)
  - 6500:  Job result (BCR analysis complete, with report URL)
  - 1:     Text note (human-visible announcement for regular Nostr clients)

Uses the `nak` CLI (https://github.com/fiatjaf/nak) for event signing and publishing.
The nsec is read from a file (mode 0600) via --sec-file, never passed as a CLI arg.
"""

import json
import os
import subprocess
import sys
import time

# NIP-90 kind constants (following Origami74 convention: result = request + 1000)
KIND_BCR_REQUEST = 5500    # Job request: "analyze workshop X"
KIND_BCR_RESULT = 6500     # Job result: 5500 + 1000
KIND_JOB_FEEDBACK = 7000   # Status updates
KIND_NIP89_ANNOUNCE = 31989  # Service discovery
KIND_TEXT_NOTE = 1         # Human-visible note

# Default relays (high-activity per nostrmash.com metrics)
DEFAULT_RELAYS = [
    "wss://nos.lol",
    "wss://relay.damus.io",
    "wss://relay.primal.net",
]

# Status values per NIP-90
STATUS_PROCESSING = "processing"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_PARTIAL = "partial"


def _nak_available() -> bool:
    """Check if nak CLI is installed."""
    result = subprocess.run(["which", "nak"], capture_output=True, text=True)
    return result.returncode == 0


def _nostr_now() -> int:
    """Current Unix timestamp (Nostr convention)."""
    return int(time.time())


def _publish_event(
    nsec_file: str,
    kind: int,
    content: str,
    tags: list,
    relays: list = None,
) -> dict:
    """Sign and publish a Nostr event via nak CLI.

    Args:
        nsec_file: Path to file containing the hex private key (mode 0600).
        kind: Nostr event kind.
        content: Event content string.
        tags: List of tag arrays, e.g. [["t","bitcoin"], ["status","success"]].
        relays: List of relay URLs. Defaults to DEFAULT_RELAYS.

    Returns:
        dict with 'success' (bool) and 'event_id' (str) or 'error' (str).
    """
    if relays is None:
        relays = DEFAULT_RELAYS

    if not _nak_available():
        return {"success": False, "error": "nak CLI not found. Install: https://github.com/fiatjaf/nak"}

    # Build nak command
    cmd = [
        "nak", "event",
        "--sec-file", nsec_file,
        "-k", str(kind),
        "-c", content,
    ]

    # Add tags — nak uses repeated --tag flags
    for tag in tags:
        tag_str = " ".join(str(t) for t in tag)
        cmd.extend(["--tag", tag_str])

    # Relays as positional args
    cmd.extend(relays)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        return {"success": False, "error": f"nak event failed: {result.stderr.strip()}"}

    # nak prints the event JSON to stdout on success
    try:
        event = json.loads(result.stdout.strip().split("\n")[-1])
        return {"success": True, "event_id": event.get("id", ""), "event": event}
    except (json.JSONDecodeError, IndexError):
        return {"success": True, "event_id": "", "raw_output": result.stdout.strip()}


def publish_nip89_announcement(nsec_file: str, relays: list = None) -> dict:
    """Publish NIP-89 service announcement (kind 31989).

    Makes the BCR Agent DVM discoverable to Nostr clients.
    Should be published once (or periodically).

    Follows Origami74 pattern: kind 31989 with ["k","5500"] tag.
    """
    content = json.dumps({
        "name": "BCR Agent",
        "about": "AI-powered Bitcoin Core PR Review Club reviewer. Runs workshops, answers questions, and compares against human IRC discussion.",
        "picture": "",
        "banner": "",
        "website": "https://github.com/Amperstrand/bcr-agent",
        "lud16": "",  # Lightning address for NIP-90 payments (future)
    })

    tags = [
        ["k", str(KIND_BCR_REQUEST)],  # Advertise we handle kind 5500
        ["t", "bitcoin"],
        ["t", "bitcoin-core"],
        ["t", "review-club"],
    ]

    return _publish_event(nsec_file, KIND_NIP89_ANNOUNCE, content, tags, relays)


def publish_processing_status(
    nsec_file: str,
    workshop_id: str,
    stage: str,
    relays: list = None,
) -> dict:
    """Publish job feedback: processing (kind 7000).

    Args:
        workshop_id: Workshop being analyzed.
        stage: Human-readable stage description (e.g. "Scraping workshop data").
    """
    content = json.dumps({"workshop_id": workshop_id, "stage": stage})

    tags = [
        ["status", STATUS_PROCESSING, stage],
        ["param", "workshop_id", workshop_id],
        ["t", "bitcoin"],
        ["t", "review-club"],
    ]

    return _publish_event(nsec_file, KIND_JOB_FEEDBACK, content, tags, relays)


def publish_job_result(
    nsec_file: str,
    workshop_id: str,
    report_url: str,
    pr_title: str = "",
    pr_url: str = "",
    summary: str = "",
    metrics: dict = None,
    relays: list = None,
) -> dict:
    """Publish NIP-90 job result (kind 6500).

    This is the primary "we're done" event. Contains the blossom URL where
    the full report is published, plus structured metrics.

    Follows NIP-90: result kind = request kind + 1000 (5500 + 1000 = 6500).
    """
    # Structured content with report URL and summary
    content_parts = [
        f"BCR Agent analysis complete for workshop #{workshop_id}.",
        f"Report: {report_url}",
    ]
    if pr_title:
        content_parts.append(f"PR: {pr_title}")
    if summary:
        content_parts.append(f"\n{summary}")

    content = "\n".join(content_parts)

    tags = [
        ["status", STATUS_SUCCESS, f"Workshop #{workshop_id} analyzed"],
        ["i", report_url, "url"],  # NIP-90 input tag: the output URL
        ["param", "workshop_id", workshop_id],
        ["output", "text/markdown"],
        ["t", "bitcoin"],
        ["t", "bitcoin-core"],
        ["t", "review-club"],
        ["t", "bcr-agent"],
    ]

    if pr_url:
        tags.append(["param", "pr_url", pr_url])

    # Add metrics as params if provided
    if metrics:
        for key, value in metrics.items():
            tags.append(["param", key, str(value)])

    return _publish_event(nsec_file, KIND_BCR_RESULT, content, tags, relays)


def publish_error(
    nsec_file: str,
    workshop_id: str,
    error_message: str,
    relays: list = None,
) -> dict:
    """Publish job feedback: error (kind 7000)."""
    tags = [
        ["status", STATUS_ERROR, error_message[:200]],
        ["param", "workshop_id", workshop_id],
        ["t", "bitcoin"],
    ]

    return _publish_event(nsec_file, KIND_JOB_FEEDBACK, error_message, tags, relays)


def publish_text_note(
    nsec_file: str,
    content: str,
    relays: list = None,
) -> dict:
    """Publish a kind 1 text note (human-visible in regular Nostr clients).

    Most Nostr clients (Damus, Amethyst, Iris, etc.) only render kind 1 events.
    Use this alongside the NIP-90 kind 6500 result for maximum visibility.
    """
    tags = [
        ["t", "bitcoin"],
        ["t", "review-club"],
        ["t", "bcr-agent"],
    ]

    return _publish_event(nsec_file, KIND_TEXT_NOTE, content, tags, relays)


def announce_completion(
    nsec_file: str,
    workshop_id: str,
    report_url: str,
    pr_title: str = "",
    metrics: dict = None,
    relays: list = None,
) -> list:
    """Full announcement sequence: publish job result + text note.

    This is the main entry point called by run.py after the pipeline completes.

    Returns:
        List of result dicts from each published event.
    """
    results = []

    # 1. NIP-90 Job Result (machine-readable)
    result = publish_job_result(
        nsec_file=nsec_file,
        workshop_id=workshop_id,
        report_url=report_url,
        pr_title=pr_title,
        metrics=metrics,
        relays=relays,
    )
    results.append({"event": "job_result", **result})

    # 2. Text note (human-visible)
    note_lines = [
        f"BCR Agent completed analysis of Bitcoin Core PR Review Club workshop #{workshop_id}.",
    ]
    if pr_title:
        note_lines.append(f"PR: {pr_title}")
    note_lines.append(f"Full report: {report_url}")

    if metrics:
        note_lines.append("")
        for key, value in metrics.items():
            note_lines.append(f"  {key}: {value}")

    result = publish_text_note(
        nsec_file=nsec_file,
        content="\n".join(note_lines),
        relays=relays,
    )
    results.append({"event": "text_note", **result})

    return results


if __name__ == "__main__":
    # Quick test: publish a test note
    nsec_file = os.environ.get("NSEC_FILE", "")
    if not nsec_file:
        print("Set NSEC_FILE env var to test")
        sys.exit(1)

    result = publish_text_note(nsec_file, "BCR Agent test post — please ignore")
    print(json.dumps(result, indent=2))
