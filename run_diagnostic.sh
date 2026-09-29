#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "ERROR: .venv not found. Run ./install.sh first."
    exit 1
fi

if [ "$#" -lt 2 ]; then
    echo "Usage:"
    echo "  ./run_diagnostic.sh ROBOT_IP ROBOT_TOKEN [MODEL]"
    echo
    echo "MODEL defaults to auto."
    exit 1
fi

IP="$1"
TOKEN="$2"
MODEL="${3:-auto}"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/diagnostic.py" \
    --ip "${IP}" \
    --token "${TOKEN}" \
    --model "${MODEL}" \
    --output "${SCRIPT_DIR}/diagnostic_result.json"
