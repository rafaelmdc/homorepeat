#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

docker build -f containers/acquisition.Dockerfile -t homorepeat-acquisition:dev .
docker build -f containers/detection.Dockerfile -t homorepeat-detection:dev .
