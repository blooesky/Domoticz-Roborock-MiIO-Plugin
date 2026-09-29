#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Installing Roborock Local Plugin for Domoticz..."
echo "Directory: ${SCRIPT_DIR}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "ERROR: ${PYTHON_BIN} was not found."
    exit 1
fi

echo "Python: $("${PYTHON_BIN}" --version 2>&1)"

if ! "${PYTHON_BIN}" -m venv --help >/dev/null 2>&1; then
    echo "ERROR: Python venv support is missing."
    echo "On Debian/Raspberry Pi OS install it with:"
    echo "  sudo apt install python3-venv"
    exit 1
fi

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating isolated virtual environment..."
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install --upgrade -r "${SCRIPT_DIR}/requirements.txt"

chmod +x \
    "${SCRIPT_DIR}/install.sh" \
    "${SCRIPT_DIR}/update.sh" \
    "${SCRIPT_DIR}/uninstall.sh" \
    "${SCRIPT_DIR}/run_diagnostic.sh" \
    "${SCRIPT_DIR}/diagnostic.py"

"${VENV_DIR}/bin/python" -m py_compile \
    "${SCRIPT_DIR}/plugin.py" \
    "${SCRIPT_DIR}/roborock_client.py" \
    "${SCRIPT_DIR}/miio_crypto_compat.py" \
    "${SCRIPT_DIR}/diagnostic.py"

"${VENV_DIR}/bin/python" - <<'PY'
import miio
from miio import RoborockVacuum
from miio_crypto_compat import CRYPTO_BACKEND, self_test

self_test()
print("python-miio import OK:", getattr(miio, "__version__", "unknown"))
print("RoborockVacuum import OK:", RoborockVacuum.__name__)
print("miIO AES-CBC backend OK:", CRYPTO_BACKEND)
PY

echo
echo "Installation completed."
echo "Restart Domoticz:"
echo "  sudo systemctl restart domoticz"
echo
echo "Then add Hardware: Roborock Local"
