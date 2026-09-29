#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Updating Roborock Local Plugin..."

if [ -d "${SCRIPT_DIR}/.git" ]; then
    cd "${SCRIPT_DIR}"
    git pull --ff-only
else
    echo "No Git repository detected; plugin source files were not downloaded."
    echo "The Python environment will still be updated."
fi

"${SCRIPT_DIR}/install.sh"

echo
echo "Restart Domoticz:"
echo "  sudo systemctl restart domoticz"
