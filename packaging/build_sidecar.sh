#!/bin/sh
# Freeze the agent into one executable named for the Rust target triple, where Tauri expects its sidecar.
# Run from the repo root inside the project venv: sh packaging/build_sidecar.sh
set -e
TRIPLE=$(rustc -vV | sed -n 's/^host: //p')
ROOT=$(python -c "import os; print(os.getcwd())")  # a native path, also under Git Bash on Windows
SEP=:
case "$TRIPLE" in *windows*) SEP=";";; esac
pyinstaller --noconfirm --clean --onefile --name agent-core \
  --paths . \
  --add-data "$ROOT/sc_activity_agent/web/templates${SEP}sc_activity_agent/web/templates" \
  --add-data "$ROOT/sc_activity_agent/web/static${SEP}sc_activity_agent/web/static" \
  --collect-submodules uvicorn --collect-data tzdata --collect-data certifi \
  --distpath packaging/dist --workpath packaging/build --specpath packaging/build \
  packaging/sidecar.py
mkdir -p src-tauri/binaries
EXT=""; case "$TRIPLE" in *windows*) EXT=".exe";; esac
cp "packaging/dist/agent-core$EXT" "src-tauri/binaries/agent-core-$TRIPLE$EXT"
echo "Built src-tauri/binaries/agent-core-$TRIPLE$EXT"
