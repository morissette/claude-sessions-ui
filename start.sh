#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "⬡  Claude Sessions UI"
echo ""

# ── Frontend ──────────────────────────────────────────────
if [ ! -d frontend/node_modules ]; then
  echo "→ Installing frontend dependencies..."
  (cd frontend && npm install)
fi

if [ ! -d frontend/dist ]; then
  echo "→ Building frontend..."
  (cd frontend && npm run build)
fi

# ── Backend ───────────────────────────────────────────────
echo "→ Starting backend on http://localhost:8765"
echo "  Prometheus metrics: http://localhost:8765/metrics"
echo "  Logs: ~/.claude/claude-sessions-ui.log"
echo ""

python3 -m backend.main
