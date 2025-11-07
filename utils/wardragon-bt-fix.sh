#!/usr/bin/env bash
#
# Fix Intel Bluetooth firmware on 22.04-based WarDragon kits
# Downloads required ibt-0040-1050 firmware files if missing.
#
# Usage:
#   chmod +x fix-intel-bt.sh
#   sudo ./fix-intel-bt.sh
#

set -euo pipefail

FW_DIR="/lib/firmware/intel"
SFI_FILE="ibt-0040-1050.sfi"
DDC_FILE="ibt-0040-1050.ddc"

SFI_URL="https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/intel/${SFI_FILE}"
DDC_URL="https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/intel/${DDC_FILE}"

# Require root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root. Try:"
    echo "  sudo $0"
    exit 1
fi

echo "[*] Checking for existing Intel Bluetooth firmware..."

if [[ -f "${FW_DIR}/${SFI_FILE}" && -f "${FW_DIR}/${DDC_FILE}" ]]; then
    echo "[✓] Both firmware files already exist:"
    echo "    ${FW_DIR}/${SFI_FILE}"
    echo "    ${FW_DIR}/${DDC_FILE}"
    echo "No action needed."
    exit 0
fi

echo "[*] Missing firmware detected. Installing now..."
mkdir -p "${FW_DIR}"
cd "${FW_DIR}"

if [[ ! -f "${SFI_FILE}" ]]; then
    echo "[*] Downloading ${SFI_FILE}..."
    wget -O "${SFI_FILE}" "${SFI_URL}"
else
    echo "[✓] ${SFI_FILE} already present."
fi

if [[ ! -f "${DDC_FILE}" ]]; then
    echo "[*] Downloading ${DDC_FILE}..."
    wget -O "${DDC_FILE}" "${DDC_URL}"
else
    echo "[✓] ${DDC_FILE} already present."
fi

echo
echo "============================================================"
echo "Firmware installation complete."
echo
echo "Next steps:"
echo "  1) Reboot your system."
echo "  2) After reboot, verify Bluetooth with:"
echo "       hcitool dev"
echo "     You should see an 'hci0' device listed."
echo "============================================================"
echo

exit 0
