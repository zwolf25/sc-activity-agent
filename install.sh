#!/bin/sh
# SC Activity Agent installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/zwolf25/sc-activity-agent/main/install.sh | sh
# Needs Python 3.11 or newer. Installs into ~/.sc-activity-agent-app (its own virtual environment), so nothing else on the
# machine changes. Your data folder is separate and is never touched by an install or update.
set -e
REPO="zwolf25/sc-activity-agent"
HOME_DIR="$HOME/.sc-activity-agent-app"
ENVIRONMENT="${1:-prod}"   # prod or sb2; locked per data folder

PY=""; FOUND=""
for c in python3.12 python3.13 python3.11 python3.14 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    FOUND=1
    rm -rf "$HOME_DIR/venv"
    # a few Pythons (for example some uv-managed builds) cannot make a venv with pip: try the next one
    if "$c" -m venv "$HOME_DIR/venv" >/dev/null 2>&1; then PY="$c"; break; fi
  fi
done
if [ -z "$FOUND" ]; then
  echo "SC Activity Agent needs Python 3.11 or newer, and none was found."
  echo
  case "$(uname)" in
    Darwin) echo "Install it, then run this installer again:"
            echo "  1. With Homebrew:  brew install python@3.12"
            echo "  2. Or download the installer from https://www.python.org/downloads/macos/" ;;
    *)      echo "Install it with your package manager, then run this installer again:"
            echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv"
            echo "  Fedora:         sudo dnf install python3" ;;
  esac
  exit 1
fi
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer was found, but it cannot create a virtual environment."
  echo "On Debian/Ubuntu run: sudo apt install python3-venv. Otherwise install Python from https://www.python.org/downloads/"
  exit 1
fi
echo "Using $($PY -V) at $(command -v $PY)"

TAG=$($PY - <<EOF
import json, urllib.request
print(json.load(urllib.request.urlopen("https://api.github.com/repos/$REPO/releases/latest"))["tag_name"])
EOF
)
echo "Installing $TAG"
"$HOME_DIR/venv/bin/python" -m pip install --quiet --upgrade pip
"$HOME_DIR/venv/bin/python" -m pip install --quiet --upgrade "https://github.com/$REPO/archive/refs/tags/$TAG.zip"

AGENT="$HOME_DIR/venv/bin/agent"
DATA="$HOME/.sc-activity-agent"
[ -f "$DATA/agent.db" ] || "$AGENT" --data-dir "$DATA" init --env "$ENVIRONMENT"
"$AGENT" --data-dir "$DATA" install-app
echo
echo "Done. Open 'SC Activity Agent' from your Applications folder (macOS: ~/Applications). It opens the console in your browser."
echo "To update later, use Settings > Check for updates in the console."
