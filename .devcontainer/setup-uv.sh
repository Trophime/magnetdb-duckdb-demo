#!/bin/bash
set -euo pipefail

# Usage: .devcontainer/setup-uv.sh [--system-site-packages]
#
#   (default)               isolated venv in ${VENV_DIR:-.venv}, on
#                           ${VENV_PYTHON:-3.14} (a version or an interpreter
#                           path, passed to `uv venv --python`); installs the
#                           magnettools wheel when the magnettools-db files
#                           are present (devcontainer)
#   --system-site-packages  venv in ${VENV_DIR:-.venv}-systempackage on
#                           /usr/bin/python3 with system site-packages
#                           (python3-magnettools in the devcontainer)
#
# The devcontainer sets VENV_DIR outside the workspace, so host and container
# venvs never mix, and VENV_PYTHON=/usr/bin/python3 (Debian's 3.13).

SYSTEM_SITE=false
case "${1:-}" in
    "") ;;
    --system-site-packages) SYSTEM_SITE=true ;;
    *)
        echo "Usage: $0 [--system-site-packages]" >&2
        exit 1
        ;;
esac

VENV="${VENV_DIR:-.venv}"
if $SYSTEM_SITE; then
    VENV="${VENV}-systempackage"
fi

echo "⚡ Starting UV-powered Isolated Setup in $VENV..."

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

# uv skips bytecode compilation by default: the first import would then
# compile pandas, dash, ... on the fly and look like a hang
export UV_COMPILE_BYTECODE="${UV_COMPILE_BYTECODE:-1}"

# --- Step 1: Create or reuse venv ---
if [[ -d "$VENV" ]]; then
    cfg="$VENV/pyvenv.cfg"
    if [[ ! -f "$cfg" ]]; then
        echo "❌ $VENV exists but pyvenv.cfg is missing — broken venv." >&2
        echo "   Remove it with: rm -rf $VENV" >&2
        exit 1
    fi
    if grep -qi "include-system-site-packages = true" "$cfg"; then
        has_system_site=true
    else
        has_system_site=false
    fi
    if [[ "$has_system_site" != "$SYSTEM_SITE" ]]; then
        echo "❌ Existing $VENV has include-system-site-packages = $has_system_site, expected $SYSTEM_SITE." >&2
        echo "   Remove it with: rm -rf $VENV  then rerun this script." >&2
        exit 1
    fi
    echo "ℹ️  Virtual environment $VENV already exists, reusing it."
elif $SYSTEM_SITE; then
    echo "🐍 Creating virtual environment with uv (system site-packages)..."
    uv venv --python /usr/bin/python3 --system-site-packages "$VENV"
else
    echo "🐍 Creating virtual environment with uv..."
    uv venv --python "${VENV_PYTHON:-3.14}" "$VENV"
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"

# --- Step 2: Install interactive tools ---
echo "📦 Installing Jupyter and Voila..."
uv pip install ipyfilechooser ipywidgets voila pandas

# --- Step 3: Install local submodules in editable mode ---
echo "🛠️  Linking development submodules..."
uv pip install -e "./python_magnetgeo"
uv pip install -e "./python_magnetcooling[fitting]"
uv pip install -e "./python_magnetrun[signal,dash,hybrid]"
uv pip install -e "./python_magnetsetup"

# --- Step 4: Install the magnettools wheel (optional, devcontainer only) ---
# libmagnettools1 comes from the image; never mix the wheel with
# python3-magnettools, hence not in the system site-packages venv.
if ! $SYSTEM_SITE && [[ -d /opt/magnettools/wheels ]]; then
    cp_tag=$(python -c 'import sys; print(f"cp{sys.version_info.major}{sys.version_info.minor}")')
    wheels=(/opt/magnettools/wheels/magnettools-*-"$cp_tag"-*.whl)
    if [[ -f "${wheels[0]}" ]]; then
        echo "🧲 Installing magnettools wheel ${wheels[0]##*/}..."
        uv pip install "${wheels[0]}"
    else
        echo "⚠️  No magnettools wheel for $cp_tag in /opt/magnettools/wheels: hoop-stress commands unavailable." >&2
    fi
fi

# --- Step 5: Install to_duckdb library and dashboard app dependencies ---
echo "📊 Installing to_duckdb and the magnetdb dashboard..."
uv pip install "./to_duckdb[test,notebook,cli]"
uv pip install "./apps/dashboards/magnetdb[test]"

echo "✅ UV Setup Complete! Activate it with: source $VENV/bin/activate"

deactivate
