#!/bin/bash
set -euo pipefail

echo "⚡ Starting UV-powered Isolated Setup..."

# --- Safeguards ---

# Check required commands
for cmd in git python3 uv; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "❌ Required command not found: $cmd" >&2
        exit 1
    fi
done

# Check minimum Python version (3.8+)
python3 - <<'EOF'
import sys
if sys.version_info < (3, 8):
    print(f"❌ Python 3.8+ required, found {sys.version}", file=sys.stderr)
    sys.exit(1)
EOF

# Ensure we are running from the repository root
if [[ ! -f ".devcontainer/setup-uv.sh" ]]; then
    echo "❌ This script must be run from the repository root." >&2
    exit 1
fi

# --- Step 0: Initialize git submodules ---
echo "📥 Initializing git submodules..."
git submodule update --init --recursive

# Verify expected submodule directories are present
for pkg in python_magnetgeo python_magnetcooling python_magnetrun python_magnetsetup; do
    if [[ ! -d "$pkg" ]]; then
        echo "❌ Submodule directory '$pkg' is missing after submodule init." >&2
        exit 1
    fi
    if [[ ! -f "$pkg/setup.py" && ! -f "$pkg/pyproject.toml" ]]; then
        echo "❌ '$pkg' has no setup.py or pyproject.toml — submodule may not have initialized correctly." >&2
        exit 1
    fi
done

# --- Step 1: Create or reuse venv ---
if [[ -d ".venv" ]]; then
    cfg=".venv/pyvenv.cfg"
    if [[ ! -f "$cfg" ]]; then
        echo "❌ .venv exists but pyvenv.cfg is missing — broken venv." >&2
        echo "   Remove it with: rm -rf .venv" >&2
        exit 1
    fi
    if ! grep -qi "include-system-site-packages = true" "$cfg"; then
        echo "❌ Existing .venv was NOT created with --system-site-packages." >&2
        echo "   Remove it with: rm -rf .venv  then rerun this script." >&2
        exit 1
    fi
    echo "ℹ️  Virtual environment already exists with system-site-packages, reusing it."
else
    echo "🐍 Creating virtual environment with uv..."
    uv venv --system-site-packages
fi

# shellcheck source=/dev/null
source .venv/bin/activate

# --- Step 2: Install interactive tools ---
echo "📦 Installing Jupyter and Voila..."
uv pip install ipyfilechooser ipywidgets voila pandas

# --- Step 3: Install local submodules in editable mode ---
echo "🛠️  Linking development submodules..."
uv pip install -e "./python_magnetgeo"
uv pip install -e "./python_magnetcooling[fitting]"
uv pip install -e "./python_magnetrun[signal,hybrid]"
uv pip install -e "./python_magnetsetup"

echo "✅ UV Setup Complete! Your environment is isolated but has access to system site packages."

deactivate
