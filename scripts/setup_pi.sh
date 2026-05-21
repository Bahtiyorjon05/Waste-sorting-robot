#!/usr/bin/env bash
# =============================================================================
# EcoSort AI - one-command Raspberry Pi setup
# =============================================================================
# Run this ONCE on the Raspberry Pi, from inside the project folder:
#
#     cd ~/ecosort-ai
#     bash scripts/setup_pi.sh
#
# It installs everything the robot needs: the camera library, GPIO library,
# and all Python dependencies (including YOLOv8). Takes 10-30 minutes the
# first time because PyTorch is large.
# =============================================================================
set -e  # stop immediately if any command fails

echo "============================================================"
echo "  EcoSort AI - Raspberry Pi setup"
echo "============================================================"

# --- 1. System packages -----------------------------------------------------
# picamera2 / libcamera : the Pi Camera driver (cannot be pip-installed well)
# gpiozero / lgpio      : control the servo + ultrasonic sensor GPIO pins
echo ""
echo "[1/4] Installing system packages (apt)..."
sudo apt update
sudo apt install -y \
    git python3-pip python3-venv \
    python3-picamera2 python3-libcamera \
    python3-gpiozero python3-lgpio

# --- 2. Python virtual environment ------------------------------------------
# --system-site-packages lets the venv ALSO see the apt-installed picamera2
# and gpiozero packages above.
echo ""
echo "[2/4] Creating Python virtual environment (.venv)..."
python3 -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate

# --- 3. Python dependencies -------------------------------------------------
echo ""
echo "[3/4] Installing Python packages (this is the slow part)..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyserial   # only needed for the optional Arduino servo backend

# --- 4. Done ----------------------------------------------------------------
echo ""
echo "[4/4] Setup complete."
echo "============================================================"
echo "  To start EcoSort AI now:"
echo ""
echo "    source .venv/bin/activate"
echo "    python -m backend.main"
echo ""
echo "  Then on your laptop open:  http://$(hostname -I | awk '{print $1}'):8000"
echo ""
echo "  To make it start automatically on power-up, see:"
echo "    scripts/ecosort.service  and  docs/SETUP.md"
echo "============================================================"
