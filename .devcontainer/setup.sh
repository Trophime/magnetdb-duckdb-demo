#!/bin/bash
set -e

echo "🚀 Starting Isolated Environment Setup..."

# 1. Create a clean venv (no system packages)
python3 -m venv .venv
source .venv/bin/activate

# 2. Upgrade pip to avoid old-version headaches
pip install --upgrade pip

# 3. THE BRIDGE: Automatically find and link the private module
# Replace 'private_module_name' with the actual name of the package in the base image
MODULE_NAME="python3-magnettools"

# Get the directory of the system-installed private module
# We run this with /usr/bin/python3 to ensure we are looking at the BASE IMAGE
SYSTEM_PKG_PATH=$(/usr/bin/python3 -c "import $MODULE_NAME, os; print(os.path.dirname($MODULE_NAME.__file__))")

if [ -z "$SYSTEM_PKG_PATH" ]; then
    echo "❌ Error: Could not find $MODULE_NAME in the base image."
    exit 1
else
    echo "🔗 Found $MODULE_NAME at $SYSTEM_PKG_PATH. Linking to venv..."
    # We link the folder into our venv's site-packages
    # We use 'python3 -c' to get the venv's own site-packages path dynamically
    VENV_SITE_PKGS=$(python3 -c "import site; print(site.getsitepackages()[0])")
    ln -s "$SYSTEM_PKG_PATH" "$VENV_SITE_PKGS/"
fi

# 4. Install your interactive tools
echo "📦 Installing Jupyter and Voila..."
pip install ipyfilechooser ipywidgets voila pandas

# 5. Install your 'Heavy Development' submodules in EDITABLE mode
# echo "🛠️ Linking development submodules..."
# pip install -e ./submodules/my-interactive-pkg

echo "✅ Setup Complete! Your environment is isolated but bridged to the private module."
