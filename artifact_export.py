#!/usr/bin/env python3
"""
BCR Agent — Artifact Exporter

Exports pipeline artifacts to a BlossomFS mount (or regular directory) with
mandatory secret scanning. Every file is scanned by secret_scanner before
being written. A manifest.json records all published blobs.

Usage:
  from artifact_export import export_artifacts

  manifest = export_artifacts(
      workshop_id="33300",
      source_dir="/opt/bcr-agent",
      dest_dir="/mnt/blossomfs/archive/33300",
  )
"""

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from secret_scanner import scan_file

# --- Artifact collection ---

ARTIFACT_PATHS = {
    "results": [
        "{workshop_id}_blind_results.json",
        "{workshop_id}_augmented_results.json",
        "{workshop_id}_blind_report.txt",
        "{workshop_id}_augmented_report.txt",
        "{workshop_id}_report.txt",
    ],
    "data": [
        "{workshop_id}_structured.json",
        "{workshop_id}_segmentation.json",
        "{workshop_id}_github_comments.json",
    ],
    "logs": [
        "/var/log/bcr-agent.log",
    ],
}

EXTRA_FILES = [
    "pipeline_metadata.json",
]


def collect_artifacts(workshop_id: str, source_dir: str) -> list:
    """Find all artifact files that exist for a workshop run."""
    artifacts = []

    for subdir, patterns in ARTIFACT_PATHS.items():
        for pattern in patterns:
            fname = pattern.format(workshop_id=workshop_id)
            if fname.startswith("/"):
                fpath = fname
            else:
                fpath = os.path.join(source_dir, subdir, fname)
            if os.path.exists(fpath):
                artifacts.append({
                    "source": fpath,
                    "category": subdir,
                    "name": os.path.basename(fpath),
                })

    return artifacts


def generate_metadata(workshop_id: str, source_dir: str) -> dict:
    """Generate pipeline metadata for the archive."""
    metadata = {
        "workshop_id": workshop_id,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_version": "bcr-agent-1.0",
        "llm_backend": "opencode + z.ai GLM-4.6",
    }

    structured_path = os.path.join(source_dir, "data", f"{workshop_id}_structured.json")
    if os.path.exists(structured_path):
        with open(structured_path) as f:
            workshop = json.load(f)
        metadata["workshop_title"] = workshop.get("title", "")
        metadata["pr_url"] = workshop.get("pr_url", "")
        metadata["pr_number"] = workshop.get("pr_number")
        metadata["host"] = workshop.get("host", "")
        metadata["author"] = workshop.get("author", "")
        metadata["total_questions"] = len(workshop.get("questions", []))

    for mode in ("blind", "augmented"):
        results_path = os.path.join(source_dir, "results", f"{workshop_id}_{mode}_results.json")
        if os.path.exists(results_path):
            with open(results_path) as f:
                results = json.load(f)
            total_time = sum(a.get("elapsed_seconds", 0) for a in results.get("answers", []))
            metadata[f"{mode}_questions_answered"] = results.get("questions_answered", 0)
            metadata[f"{mode}_total_time_seconds"] = round(total_time, 1)

    return metadata


def export_artifacts(
    workshop_id: str,
    source_dir: str,
    dest_dir: str,
    blossom_server: str = "https://blossom.psbt.me",
) -> dict:
    """Export all pipeline artifacts to dest_dir with secret scanning.

    Each file is scanned by secret_scanner. Blocked files are skipped.
    Sanitized files are written. A manifest.json is generated.

    Returns:
        {
            "manifest": {archive metadata + file list with sha256},
            "blocked": [filenames],
            "redacted": [{filename, count}],
            "clean": [filenames],
            "errors": [{filename, error}],
        }
    """
    os.makedirs(dest_dir, exist_ok=True)

    metadata = generate_metadata(workshop_id, source_dir)

    meta_path = os.path.join(source_dir, "pipeline_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    artifacts = collect_artifacts(workshop_id, source_dir)

    manifest_files = []
    blocked = []
    redacted = []
    clean = []
    errors = []

    for artifact in artifacts:
        src = artifact["source"]
        name = artifact["name"]
        category = artifact["category"]
        dest_subdir = os.path.join(dest_dir, category)
        os.makedirs(dest_subdir, exist_ok=True)
        dest_path = os.path.join(dest_subdir, name)

        sanitized, findings = scan_file(src)

        if sanitized is None:
            reason = findings[0].get("type", "unknown") if findings else "unknown"
            blocked.append({"name": name, "reason": reason})
            continue

        if findings:
            redacted.append({"name": name, "count": len(findings),
                             "types": [f["type"] for f in findings]})

        try:
            with open(dest_path, "w") as f:
                f.write(sanitized)
            clean.append(name)
            sha256 = hashlib.sha256(sanitized.encode()).hexdigest()
            size = len(sanitized.encode())
            manifest_files.append({
                "name": name,
                "category": category,
                "path": f"{category}/{name}",
                "sha256": sha256,
                "size": size,
                "redacted": len(findings) > 0,
                "blossom_url": f"{blossom_server}/{sha256}",
            })
        except Exception as e:
            errors.append({"name": name, "error": str(e)})

    manifest = {
        "workshop_id": workshop_id,
        "workshop_title": metadata.get("workshop_title", ""),
        "pr_url": metadata.get("pr_url", ""),
        "exported_at": metadata.get("exported_at", ""),
        "blossom_server": blossom_server,
        "files": manifest_files,
        "summary": {
            "total": len(artifacts),
            "clean": len(clean),
            "redacted": len(redacted),
            "blocked": len(blocked),
            "errors": len(errors),
        },
    }

    manifest_path = os.path.join(dest_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"ARTIFACT EXPORT COMPLETE — Workshop #{workshop_id}")
    print(f"{'=' * 60}")
    print(f"  Destination: {dest_dir}")
    print(f"  Files published: {len(clean)}")
    print(f"  Files redacted: {len(redacted)}")
    print(f"  Files blocked: {len(blocked)}")
    if blocked:
        print("  BLOCKED (secrets prevented from publishing):")
        for b in blocked:
            print(f"    ✗ {b['name']} ({b['reason']})")
    if redacted:
        print("  REDACTED (secrets scrubbed before publishing):")
        for r in redacted:
            print(f"    ⚠ {r['name']} ({r['count']} secrets removed)")
    print(f"  Manifest: {manifest_path}")
    print(f"{'=' * 60}\n")

    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "blocked": blocked,
        "redacted": redacted,
        "clean": clean,
        "errors": errors,
    }


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python artifact_export.py <workshop_id> <source_dir> <dest_dir>")
        sys.exit(1)

    result = export_artifacts(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"\nManifest: {result['manifest_path']}")
