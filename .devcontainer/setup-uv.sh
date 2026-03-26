#!/bin/bash
set -e

echo "⚡ Starting UV-powered Isolated Setup..."

# 1. Create a clean virtual environment (No system-site-packages)
# uv creates this in the .venv directory by default
uv venv

# 2. Activate the environment
source .venv/bin/activate

# 3. THE BRIDGE: Locate the private module in the base image
# Replace 'private_module_name' with the actual name
MODULE_NAME="private_module_name"

# We ask the SYSTEM python where the module is
SYSTEM_MODULE_PATH=$(/usr/bin/python3 -c "import $MODULE_NAME, os; print(os.path.dirname($MODULE_NAME.__file__))")

if [ -z "$SYSTEM_MODULE_PATH" ]; then
    echo "❌ Error: Could not find $MODULE_NAME in the base image."
    exit 1
fi

# Find the venv's site-packages directory
VENV_SITE_PKGS=$(python3 -c "import site; print(site.getsitepackages()[0])")

# Create the symlink
echo "🔗 Bridging $MODULE_NAME from $SYSTEM_MODULE_PATH..."
ln -s "$SYSTEM_MODULE_PATH" "$VENV_SITE_PKGS/"

# 4. Install dependencies and submodules using 'uv sync' or 'uv pip'
# 'uv pip install' is the most direct equivalent to your pip workflow
echo "📦 Installing Jupyter, Voila, and Widgets..."
uv pip install ipywidgets voila pandas

# 5. Install your 'Heavy Development' submodules in EDITABLE mode
echo "🛠️ Linking development submodules..."
uv pip install -e ./submodules/heavy-dev-pkg

echo "✅ UV Setup Complete!"
