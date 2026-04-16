#!/usr/bin/env bash
# Run Claude Sessions UI with generated fixture data (no real ~/.claude/ needed).
# Usage: ./demo.sh [output-dir]
#   output-dir  where to write fixture sessions (default: /tmp/claude-demo)
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

DEMO_DIR="${1:-/tmp/claude-demo}"

echo "Generating fixture sessions in $DEMO_DIR ..."
python3 fixtures/generate.py --output-dir "$DEMO_DIR"

echo ""
echo "Starting Claude Sessions UI with demo data..."
echo "  Open http://localhost:8765"
echo ""
CLAUDE_DIR="$DEMO_DIR/projects" ./start.sh
