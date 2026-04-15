#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "Claude Sessions UI — Docker"
echo ""

case "${1:-up}" in
  build)
    echo "Building Docker image..."
    docker compose build
    ;;
  up)
    echo "Starting container at http://localhost:8765"
    docker compose up -d
    echo "  Logs: ./docker.sh logs"
    ;;
  down)
    docker compose down
    ;;
  logs)
    docker compose logs -f
    ;;
  *)
    echo "Usage: $0 [build|up|down|logs]"
    exit 1
    ;;
esac
