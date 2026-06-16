#!/usr/bin/env bash
# BCR Agent — Pre-commit secret scanner
#
# Uses gitleaks if available, falls back to a grep-based check for critical patterns.
# Blocks commits that contain secrets (nsec, Cashu tokens, API keys, etc.)
#
# Install:  bash scripts/install-hooks.sh
# Or:       ln -sf ../../scripts/pre-commit.sh .git/hooks/pre-commit && chmod +x scripts/pre-commit.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# --- Gitleaks path (preferred) ---
if command -v gitleaks &> /dev/null; then
    GITLEAKS="gitleaks"
elif [ -f "/usr/local/bin/gitleaks" ]; then
    GITLEAKS="/usr/local/bin/gitleaks"
elif [ -f "$HOME/.local/bin/gitleaks" ]; then
    GITLEAKS="$HOME/.local/bin/gitleaks"
else
    GITLEAKS=""
fi

if [ -n "$GITLEAKS" ]; then
    # --- Gitleaks scan (authoritative) ---
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    if "$GITLEAKS" protect --staged --redact -c "$REPO_ROOT/.gitleaks.toml" 2>&1; then
        echo -e "${GREEN}✓ gitleaks: no secrets detected${NC}"
        exit 0
    else
        EXIT_CODE=$?
        echo -e "${RED}✗ gitleaks detected potential secrets in staged files!${NC}"
        echo -e "${YELLOW}Review the findings above. If false positive, add to .gitleaks.toml [allowlist].${NC}"
        echo -e "${YELLOW}To bypass (NOT RECOMMENDED): git commit --no-verify${NC}"
        exit $EXIT_CODE
    fi
fi

# --- Fallback: grep-based check (no gitleaks installed) ---
echo -e "${YELLOW}⚠ gitleaks not found — running basic grep-based secret check${NC}"
echo -e "${YELLOW}  Install gitleaks for comprehensive scanning: https://github.com/gitleaks/gitleaks${NC}"

STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -v -E '\.gitignore|\.gitleaks\.toml|README\.md|config\.example\.json' || true)

if [ -z "$STAGED_FILES" ]; then
    exit 0
fi

PATTERNS=(
    'nsec1[023456789acdefghjklmnpqrstuvwxyz]{58}'
    'cashu[AB][a-zA-Z0-9+/=]{20,}'
    '(ZAI_API_KEY|Z_AI_API_KEY|HCLOUD_TOKEN|HETZNER_TOKEN)["\s:=]+[A-Za-z0-9._]{20,}'
    '(gho_|ghp_|github_pat_)[A-Za-z0-9_]{36,}'
    '[a-f0-9]{32}\.[A-Za-z0-9]{16}'
    'BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY'
)

FOUND=0
for file in $STAGED_FILES; do
    [ -f "$file" ] || continue
    for pattern in "${PATTERNS[@]}"; do
        if grep -qE "$pattern" "$file" 2>/dev/null; then
            echo -e "${RED}✗ Potential secret in $file (pattern: $pattern)${NC}"
            grep -nE "$pattern" "$file" 2>/dev/null | head -3
            FOUND=1
        fi
    done
done

if [ "$FOUND" -eq 1 ]; then
    echo -e "${RED}Commit blocked: potential secrets detected.${NC}"
    echo -e "${YELLOW}Install gitleaks for better accuracy, or review manually.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Basic secret check passed (install gitleaks for full coverage)${NC}"
exit 0
