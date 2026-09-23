#!/usr/bin/env bash
# ==============================================================================
# One-Click Environment Setup Script
# Re-creates the virtual environment (.venv) and installs all dependencies
# ==============================================================================

set -e

echo "🚀 Setting up Python virtual environment..."

# 1. Create .venv if it doesn't exist
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "✅ Created .venv directory"
else
    echo "ℹ️ Existing .venv directory found"
fi

# 2. Upgrade pip and install requirements
echo "📦 Installing requirements..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 3. Create .env from template if missing
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "ℹ️ Created .env from .env.example"
fi

echo ""
echo "🎉 Virtual environment ready!"
echo "👉 Run: .venv/bin/python app.py"
echo "👉 Open: http://127.0.0.1:5050"
