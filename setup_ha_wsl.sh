#!/bin/bash
set -e

echo "Setting up Home Assistant in WSL..."

# Update package lists
sudo apt-get update -qq

# Install dependencies
sudo apt-get install -y python3 python3-pip python3-venv python3-dev build-essential libssl-dev libffi-dev

# Create virtual environment
python3 -m venv /mnt/c/Users/tolaa/Source/Repos/homeassistant_alpha/ha_wsl_env

# Activate and install Home Assistant
source /mnt/c/Users/tolaa/Source/Repos/homeassistant_alpha/ha_wsl_env/bin/activate
pip3 install wheel
pip3 install homeassistant

echo "Home Assistant installed successfully in WSL"
