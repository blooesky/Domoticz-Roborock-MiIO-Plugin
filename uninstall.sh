#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Removing the isolated Roborock Python environment..."
rm -rf "${SCRIPT_DIR}/.venv"
find "${SCRIPT_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +

echo "The plugin source folder and Domoticz devices were not deleted."
echo "Remove the Roborock Local hardware from Domoticz before deleting this folder."
