#!/bin/bash
set -e

echo "🚀 Starting Isolated Environment Setup..."

# 0. Initialize git submodules (required in GitHub Codespaces)
echo "📥 Initializing git submodules..."
git submodule update --init

# 1. Create a clean venv (no system packages)
python3 -m venv .venv --system-site-packages
# shellcheck source=/dev/null
source .venv/bin/activate

# 2. Upgrade pip to avoid old-version headaches
pip install --upgrade pip


# 4. Install your interactive tools
echo "📦 Installing Jupyter and Voila..."
pip install ipyfilechooser ipywidgets voila pandas

# 5. Install your 'Heavy Development' submodules in EDITABLE mode
# echo "🛠️ Linking development submodules..."
# pip install -e ./submodules/my-interactive-pkg
pip install -e "./python_magnetgeo"
pip install -e "./python_magnetcooling[fitting]"
pip install -e "./python_magnetrun[signal]"

echo "✅ Setup Complete! Your environment is isolated but has access to system site packages."

deactivate
