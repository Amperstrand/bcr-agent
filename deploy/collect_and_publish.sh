#!/bin/bash
#
# collect_and_publish.sh — Post-agent collection & publishing script.
#
# Runs AFTER the autonomous opencode session finishes. Collects all output
# files from /workspace/results/, scans for secrets, uploads to Blossom,
# publishes to Nostr, and exports the session for analysis.
#
# Environment variables (set by bootstrap-vm.sh):
#   WORKSHOP_ID   — Bitcoin Core PR Review Club workshop number (e.g. 33300)
#   MODEL         — LLM model used (e.g. glm-4.6)
#   NSEC_FILE     — Path to Nostr nsec file (default: /opt/bcr-agent-config/bot_nsec)
#
# Internal variables (set during execution):
#   BLOSSOM_URL   — Set by step 4, used by step 5
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESULTS_DIR="/workspace/results"
BCR_AGENT_DIR="/opt/bcr-agent"
NSEC_FILE="${NSEC_FILE:-/opt/bcr-agent-config/bot_nsec}"
BLOSSOM_SERVER="${BLOSSOM_SERVER:-https://blossom.psbt.me}"
BLOSSOMFS_MOUNT="/mnt/blossomfs"
NPUB_HEX="9a515b0f08d554b582e54202c7ca0e6ee56d81559957cbf9b40047d391b95fd5"

# Validate required environment variables
if [ -z "${WORKSHOP_ID:-}" ]; then
    echo "ERROR: WORKSHOP_ID environment variable is not set"
    exit 1
fi
if [ -z "${MODEL:-}" ]; then
    echo "ERROR: MODEL environment variable is not set"
    exit 1
fi
if [ ! -f "$NSEC_FILE" ]; then
    echo "ERROR: NSEC file not found at $NSEC_FILE"
    echo "       Set NSEC_FILE env var to the correct path"
    exit 1
fi

FULL_REPORT="${RESULTS_DIR}/full_report.md"
BLOSSOM_URL=""

echo ""
echo "============================================================"
echo "BCR AGENT — COLLECT & PUBLISH"
echo "  Workshop: #${WORKSHOP_ID}"
echo "  Model:    ${MODEL}"
echo "  Results:  ${RESULTS_DIR}"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Verify results directory exists and has files
# ---------------------------------------------------------------------------
echo "[1/7] Verifying results directory..."

if [ ! -d "$RESULTS_DIR" ]; then
    echo "  ERROR: Results directory ${RESULTS_DIR} does not exist"
    echo "  The opencode agent may not have produced output."
    exit 1
fi

# Count regular files (exclude subdirectories)
FILE_COUNT=$(find "$RESULTS_DIR" -maxdepth 1 -type f | wc -l)
if [ "$FILE_COUNT" -eq 0 ]; then
    echo "  ERROR: No files found in ${RESULTS_DIR}"
    echo "  The opencode agent session may have failed."
    # List the directory for debugging
    echo "  Directory contents:"
    ls -la "$RESULTS_DIR" 2>/dev/null || echo "  (cannot list)"
    exit 1
fi

echo "  Found ${FILE_COUNT} file(s) in ${RESULTS_DIR}"
ls -la "$RESULTS_DIR/"
echo ""

# ---------------------------------------------------------------------------
# Step 2: Run secret scanner on ALL files — abort if any secrets found
# ---------------------------------------------------------------------------
echo "[2/7] Scanning all files for secrets..."

cd "$BCR_AGENT_DIR"

SCAN_OUTPUT=$(python3 -c "
import os, sys

sys.path.insert(0, '/opt/bcr-agent')
from secret_scanner import scan_file

results_dir = '${RESULTS_DIR}'
blocked = []
findings_total = 0
scanned = 0

for fname in sorted(os.listdir(results_dir)):
    path = os.path.join(results_dir, fname)
    if not os.path.isfile(path):
        continue
    # Skip the report we may be regenerating
    if fname == 'full_report.md':
        continue
    scanned += 1
    sanitized, findings = scan_file(path)
    if sanitized is None:
        blocked.append(fname)
        print(f'BLOCKED: {fname} — file must not be published', file=sys.stderr)
        findings_total += 1
    elif findings:
        print(f'WARN: {fname} — {len(findings)} secret(s) redacted', file=sys.stderr)
        findings_total += len(findings)

if blocked:
    print(f'FATAL: {len(blocked)} file(s) BLOCKED', file=sys.stderr)
    sys.exit(1)
if findings_total > 0:
    print(f'FATAL: {findings_total} secret(s) detected — will not publish', file=sys.stderr)
    sys.exit(1)

print(f'All {scanned} files clean')
" 2>&1) || {
    echo "  SECRET SCAN FAILED — ABORTING PUBLISH"
    echo "  Details:"
    echo "  ${SCAN_OUTPUT//$'\n'/$'\n'  }"
    echo ""
    echo "  All files in ${RESULTS_DIR} are preserved for debugging."
    echo "  No content was uploaded or published."
    exit 1
}

echo "  $SCAN_OUTPUT"
echo "  All output files are clean — safe to publish."
echo ""

# ---------------------------------------------------------------------------
# Step 3: Combine all result files into a single report
# ---------------------------------------------------------------------------
echo "[3/7] Building combined full report..."

# Build the report header
cat > "$FULL_REPORT" << REPORT_HEADER
# BCR Agent — Workshop #${WORKSHOP_ID}

**Model:** ${MODEL}
**Mode:** ${MODE:-autonomous}
**Version:** [\`${BCR_VERSION:-unknown}\`](https://github.com/Amperstrand/bcr-agent/commit/${BCR_VERSION:-main})
**Machine:** ${MACHINE_SPECS:-unknown}
**Generated:** $(date -u +"%Y-%m-%dT%H:%M:%SZ")

---

REPORT_HEADER

# Define the standard result files in display order
REPORT_SECTIONS=(
    "summary.md"
    "q1.md" "q2.md" "q3.md" "q4.md"
    "q5.md" "q6.md" "q7.md" "q8.md"
    "recommendations.md"
    "journal.md"
)

SECTION_COUNT=0
MISSING_SECTIONS=()

for section in "${REPORT_SECTIONS[@]}"; do
    section_path="${RESULTS_DIR}/${section}"
    if [ -f "$section_path" ]; then
        # Add a separator before each section
        {
            echo ""
            echo "---"
            echo ""
            cat "$section_path"
        } >> "$FULL_REPORT"
        SECTION_COUNT=$((SECTION_COUNT + 1))
        echo "  Included: ${section}"
    else
        MISSING_SECTIONS+=("$section")
    fi
done

# Also append any other .md files not in the standard list
{
    echo ""
    echo "---"
    echo ""
} >> "$FULL_REPORT"
for f in "$RESULTS_DIR"/*.md; do
    [ -f "$f" ] || continue  # handle glob no-match
    fname=$(basename "$f")
    # Skip files already included and the report itself
    case "$fname" in
        summary.md|q1.md|q2.md|q3.md|q4.md|q5.md|q6.md|q7.md|q8.md|recommendations.md|journal.md|full_report.md)
            continue
            ;;
    esac
    {
        echo "## Appendix: ${fname}"
        echo ""
        cat "$f"
        echo ""
    } >> "$FULL_REPORT"
    SECTION_COUNT=$((SECTION_COUNT + 1))
    echo "  Included: ${fname} (appendix)"
done

# Report missing sections
if [ ${#MISSING_SECTIONS[@]} -gt 0 ]; then
    echo "  Note: missing expected files: ${MISSING_SECTIONS[*]}"
fi

REPORT_SIZE=$(stat --printf="%s" "$FULL_REPORT" 2>/dev/null || stat -f%z "$FULL_REPORT" 2>/dev/null || echo "?")
echo "  Combined report: ${SECTION_COUNT} section(s), ${REPORT_SIZE} bytes"
echo "  Saved to: ${FULL_REPORT}"
echo ""

# ---------------------------------------------------------------------------
# Step 4: Upload full report to Blossom
# ---------------------------------------------------------------------------
echo "[4/7] Uploading report to Blossom..."

set +e
BLOSSOM_OUTPUT=$(python3 -c "
import json, sys
sys.path.insert(0, '/opt/bcr-agent')
from blossom_publisher import upload_to_blossom

result = upload_to_blossom(
    file_path='${FULL_REPORT}',
    nsec_file='${NSEC_FILE}',
    server_url='${BLOSSOM_SERVER}',
    content_type='text/markdown',
)
print(json.dumps(result))
" 2>&1)
BLOSSOM_EXIT=$?
set -e

if [ $BLOSSOM_EXIT -ne 0 ]; then
    echo "  BLOSSOM UPLOAD FAILED"
    echo "  Details:"
    echo "$BLOSSOM_OUTPUT" | sed 's/^/    /'
    echo ""
    echo "  Files preserved in ${RESULTS_DIR} for debugging."
    exit 1
fi

# Extract the URL from the JSON result
BLOSSOM_URL=$(echo "$BLOSSOM_OUTPUT" | python3 -c "
import json, sys
# Find the JSON line (skip any status prints)
for line in sys.stdin:
    line = line.strip()
    if line.startswith('{'):
        data = json.loads(line)
        url = data.get('url', '')
        if url:
            print(url)
            break
        # Fallback: construct from sha256
        sha = data.get('sha256', '')
        if sha:
            print('${BLOSSOM_SERVER}/' + sha)
            break
")

if [ -z "$BLOSSOM_URL" ]; then
    echo "  ERROR: Could not extract Blossom URL from upload result"
    echo "  Raw output: $BLOSSOM_OUTPUT"
    exit 1
fi

echo "  Published to Blossom: ${BLOSSOM_URL}"
echo ""

# ---------------------------------------------------------------------------
# Step 5: Publish completion to Nostr
# ---------------------------------------------------------------------------
echo "[5/7] Publishing completion to Nostr..."

set +e
NOSTR_OUTPUT=$(python3 -c "
import json, sys
sys.path.insert(0, '/opt/bcr-agent')
from nostr_publisher import announce_completion

results = announce_completion(
    nsec_file='${NSEC_FILE}',
    workshop_id='${WORKSHOP_ID}',
    report_url='${BLOSSOM_URL}',
    metrics={
        'model': '${MODEL}',
        'mode': '${MODE:-autonomous}',
        'version': '${BCR_VERSION:-unknown}',
        'machine': '${MACHINE_SPECS:-unknown}',
        'sections': '${SECTION_COUNT}',
        'report_bytes': '${REPORT_SIZE}',
    },
)

for r in results:
    event_type = r.get('event', 'unknown')
    success = r.get('success', False)
    event_id = r.get('event_id', r.get('raw_output', ''))[:16]
    status = 'OK' if success else 'FAILED'
    print(f'  {event_type}: {status} ({event_id}...)')

print(json.dumps(results))
" 2>&1)
NOSTR_EXIT=$?
set -e

# Print the per-event status lines from the output
echo "$NOSTR_OUTPUT" | grep -E '^\s+(job_result|text_note):' || true

if [ $NOSTR_EXIT -ne 0 ]; then
    echo "  WARNING: Nostr publishing encountered errors"
    echo "  Blossom report is still available: ${BLOSSOM_URL}"
    echo "$NOSTR_OUTPUT" | sed 's/^/    /'
    # Don't abort — Blossom upload succeeded, that's the primary artifact
else
    echo "  Nostr events published successfully"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 6: Export the opencode session for analysis
# ---------------------------------------------------------------------------
echo "[6/7] Exporting opencode session..."

SESSION_EXPORT="${RESULTS_DIR}/session.json"
if command -v opencode &>/dev/null; then
    SESSION_ID=$(sqlite3 /root/.local/share/opencode/opencode.db "SELECT id FROM session ORDER BY time_created DESC LIMIT 1;" 2>/dev/null || echo "")
    if [ -n "$SESSION_ID" ]; then
        opencode export "$SESSION_ID" --sanitize > "$SESSION_EXPORT" 2>/dev/null || {
            echo "  Note: 'opencode export' failed — skipping"
            rm -f "$SESSION_EXPORT"
        }
    else
        echo "  Note: could not find session ID — skipping export"
    fi
    if [ -f "$SESSION_EXPORT" ] && [ -s "$SESSION_EXPORT" ]; then
        SESSION_SIZE=$(stat --printf="%s" "$SESSION_EXPORT" 2>/dev/null || stat -f%z "$SESSION_EXPORT" 2>/dev/null || echo "?")
        echo "  Session exported: ${SESSION_EXPORT} (${SESSION_SIZE} bytes)"

        echo "  Uploading session transcript to Blossom..."
        set +e
        SESSION_BLOSSOM=$(python3 -c "
import json, sys
sys.path.insert(0, '/opt/bcr-agent')
from blossom_publisher import upload_to_blossom
result = upload_to_blossom(
    file_path='${SESSION_EXPORT}',
    nsec_file='${NSEC_FILE}',
    server_url='${BLOSSOM_SERVER}',
    content_type='application/json',
)
print(result.get('url', ''))
" 2>&1)
        set -e
        if echo "$SESSION_BLOSSOM" | grep -q "blossom.psbt.me"; then
            echo "  Session on Blossom: ${SESSION_BLOSSOM}"
            echo "${SESSION_BLOSSOM}" > "${RESULTS_DIR}/.session_blossom_url"
        else
            echo "  Session upload failed (non-critical)"
        fi
    fi
else
    echo "  Note: opencode CLI not found — session export skipped"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 7: Copy artifacts to BlossomFS if mounted
# ---------------------------------------------------------------------------
echo "[7/7] Archiving artifacts to BlossomFS..."

if mountpoint -q "$BLOSSOMFS_MOUNT" 2>/dev/null || \
   grep -q "$BLOSSOMFS_MOUNT" /proc/mounts 2>/dev/null; then
    MODEL_SAFE=$(echo "${MODEL}" | tr '/' '-')
    ARCHIVE_PATH="${BLOSSOMFS_MOUNT}/public/${NPUB_HEX}/servers/blossom.psbt.me/by-sha256/bcr-agent-${WORKSHOP_ID}-${MODEL_SAFE}"

    mkdir -p "$ARCHIVE_PATH" 2>/dev/null || {
        echo "  WARNING: Could not create archive directory: ${ARCHIVE_PATH}"
    }

    if [ -d "$ARCHIVE_PATH" ]; then
        # Copy all results (including the new report and session)
        cp -r "$RESULTS_DIR"/* "$ARCHIVE_PATH"/ 2>/dev/null || \
            echo "  WARNING: Some files could not be copied to BlossomFS"

        ARCHIVE_COUNT=$(find "$ARCHIVE_PATH" -type f | wc -l)
        echo "  Archived ${ARCHIVE_COUNT} file(s) to BlossomFS"
        echo "  Path: ${ARCHIVE_PATH}"
    fi
else
    echo "  BlossomFS not mounted at ${BLOSSOMFS_MOUNT} — skipping archive"
    echo "  (all artifacts remain in ${RESULTS_DIR})"
fi
echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

# Get final file listing
FINAL_FILE_COUNT=$(find "$RESULTS_DIR" -maxdepth 1 -type f | wc -l)
FINAL_DIR_SIZE=$(du -sh "$RESULTS_DIR" 2>/dev/null | cut -f1 || echo "?")

echo "============================================================"
echo "COLLECTION & PUBLISH COMPLETE"
echo "============================================================"
echo ""
echo "  Workshop:       #${WORKSHOP_ID}"
echo "  Model:          ${MODEL}"
echo "  Files collected: ${FINAL_FILE_COUNT} (${FINAL_DIR_SIZE})"
echo "  Report sections: ${SECTION_COUNT}"
echo "  Report size:     ${REPORT_SIZE} bytes"
echo ""
echo "  Blossom URL:     ${BLOSSOM_URL}"
echo "  Session export:  ${SESSION_EXPORT}"
echo ""
echo "  Results dir:     ${RESULTS_DIR}"
echo "  No files were deleted — all preserved for debugging."
echo ""
echo "============================================================"
