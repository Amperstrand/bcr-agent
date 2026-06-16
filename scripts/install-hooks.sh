#!/usr/bin/env bash
# Installs git hooks for BCR Agent
# Usage: bash scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

echo "Installing pre-commit hook..."
chmod +x "$REPO_ROOT/scripts/pre-commit.sh"
ln -sf "$REPO_ROOT/scripts/pre-commit.sh" "$HOOKS_DIR/pre-commit"
echo "  ✓ pre-commit → scripts/pre-commit.sh"

# Check for gitleaks
if ! command -v gitleaks &> /dev/null; then
    echo ""
    echo "⚠ gitleaks is not installed."
    echo "  Install it for comprehensive secret scanning:"
    echo "    macOS:  brew install gitleaks"
    echo "    Linux:  https://github.com/gitleaks/gitleaks/releases"
    echo ""
    echo "  A basic grep-based fallback is active until then."
fi

echo ""
echo "Hooks installed successfully."
