#!/bin/sh
# ===========================================================================
# check-static-site.sh — Validate that docs/ is deployable from BOTH:
#   1. GitHub Pages under /bcr-agent/
#   2. A Nostr NIP-5A nsite served from /
#
# What it checks:
#   - docs/ directory exists
#   - docs/index.html exists
#   - No hardcoded /bcr-agent/ absolute paths remain (break under nsite root)
#   - No root-absolute local asset paths like href="/style.css" (break under
#     either deployment; they only resolve from one of the two roots)
#   - Every local asset referenced from index.html resolves on disk
#
# Exit codes:
#   0 = clean, 1 = problems found, 2 = structural failure (no docs/)
#
# Usage:
#   ./scripts/check-static-site.sh
#   ./scripts/check-static-site.sh /path/to/other/site/root
# ===========================================================================
set -eu

# Resolve repo root (parent of scripts/ dir) unless an argument is given.
if [ "$#" -ge 1 ]; then
  ROOT="$1"
else
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fi

DOCS_DIR="$ROOT/docs"
INDEX="$DOCS_DIR/index.html"

errors=0
warnings=0

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

# --- Structural checks -----------------------------------------------------

if [ ! -d "$DOCS_DIR" ]; then
  red "FAIL: docs/ directory not found at $DOCS_DIR"
  exit 2
fi
green "OK: docs/ directory exists"

if [ ! -f "$INDEX" ]; then
  red "FAIL: docs/index.html not found"
  exit 2
fi
green "OK: docs/index.html exists"

# --- Check 1: hardcoded /bcr-agent/ paths ----------------------------------
# Any literal /bcr-agent/ in a local file is a GitHub-Pages-only assumption
# and will 404 when the same files are served from an nsite root (/).

printf '\n%s\n' "$(bold 'Checking for hardcoded /bcr-agent/ paths...')"
gh_hits=0
# shellcheck disable=SC2016
while IFS= read -r line; do
  [ -z "$line" ] && continue
  yellow "WARN: $line"
  gh_hits=$((gh_hits + 1))
done <<EOF
$(grep -rn --exclude-dir='.*' '/bcr-agent/' "$DOCS_DIR" 2>/dev/null || true)
EOF

if [ "$gh_hits" -eq 0 ]; then
  green "OK: no hardcoded /bcr-agent/ paths found"
else
  warnings=$((warnings + gh_hits))
  printf '  -> Found %d hardcoded /bcr-agent/ reference(s). Use relative paths instead.\n' "$gh_hits"
fi

# --- Check 2: root-absolute local asset paths ------------------------------
# href="/foo" or src="/foo" resolve to the domain root, which differs between
# GitHub Pages (/bcr-agent/) and an nsite root (/). These break in at least
# one of the two deployments. Protocol-relative (//) and http(s):// are fine.

printf '\n%s\n' "$(bold 'Checking for root-absolute local asset paths...')"
root_abs_hits=0
# Match href="/..." or src="/..." but NOT href="//" or http(s)://
# Pattern: (href|src)="/ followed by a char that is NOT another slash.
while IFS= read -r line; do
  [ -z "$line" ] && continue
  yellow "WARN: $line"
  root_abs_hits=$((root_abs_hits + 1))
done <<EOF
$(grep -rEn '(href|src)="\/[^/]' "$DOCS_DIR" 2>/dev/null || true)
EOF

if [ "$root_abs_hits" -eq 0 ]; then
  green "OK: no root-absolute local asset paths found"
else
  warnings=$((warnings + root_abs_hits))
  printf '  -> Found %d root-absolute path(s). Use relative (no leading slash) paths.\n' "$root_abs_hits"
fi

# --- Check 3: local asset references resolve -------------------------------
# Extract href=/src= references that point to local files (no scheme, no
# protocol-relative, no fragment-only), strip query strings, and verify each
# exists relative to docs/.

printf '\n%s\n' "$(bold 'Checking local asset references resolve...')"
checked=0
missing=0

# Use perl if available for robust extraction; fall back to grep/sed.
extract_refs() {
  if command -v perl >/dev/null 2>&1; then
    perl -ne 'while (m{(?:href|src)="([^"]+)"}g) { my $r=$1; $r=~s/\?.*$//; print "$r\n" }' "$INDEX"
  else
    grep -oE '(href|src)="[^"]+"' "$INDEX" \
      | sed -E 's/.*="([^"]+)".*/\1/' \
      | sed -E 's/\?.*$//'
  fi
}

extract_refs | while IFS= read -r ref; do
  [ -z "$ref" ] && continue
  # Skip external and protocol-relative and fragment/data/mailto
  case "$ref" in
    http://*|https://*|//*|'#'*|data:*|mailto:*) continue ;;
  esac
  # Strip a leading ./ for resolution
  target="${DOCS_DIR}/${ref#./}"
  checked=$((checked + 1))
  if [ ! -e "$target" ]; then
    red "FAIL: index.html references '$ref' but $target does not exist"
    missing=$((missing + 1))
  fi
done
# Note: the while-loop runs in a subshell due to the pipe, so the counters
# above don't propagate. Re-derive a simple pass/fail here.
missing_recheck=0
extract_refs | while IFS= read -r ref; do
  [ -z "$ref" ] && continue
  case "$ref" in
    http://*|https://*|//*|'#'*|data:*|mailto:*) continue ;;
  esac
  target="${DOCS_DIR}/${ref#./}"
  [ -e "$target" ] || printf '%s\n' "$ref"
done | grep -c . >/tmp/bcr_check_missing.$$ 2>/dev/null || echo 0 >/tmp/bcr_check_missing.$$
missing_recheck=$(cat /tmp/bcr_check_missing.$$ 2>/dev/null || echo 0)
rm -f /tmp/bcr_check_missing.$$

total_refs=$(extract_refs | grep -cE '.' || true)
local_refs=$(extract_refs | grep -cvE '^(https?:|//|#|data:|mailto:)' || true)

if [ "$missing_recheck" -eq 0 ]; then
  green "OK: all $local_refs local asset reference(s) resolve"
else
  errors=$((errors + missing_recheck))
fi

# --- Summary ---------------------------------------------------------------

printf '\n%s\n' "$(bold 'Summary')"
printf '  warnings: %d\n' "$warnings"
printf '  errors:   %d\n' "$errors"

if [ "$errors" -gt 0 ]; then
  red "RESULT: FAIL (missing assets)"
  exit 1
fi

if [ "$warnings" -gt 0 ]; then
  yellow "RESULT: OK with warnings (paths work on GH Pages but may break on nsite root)"
  exit 0
fi

green "RESULT: CLEAN — docs/ is deployable from both /bcr-agent/ and /"
exit 0
