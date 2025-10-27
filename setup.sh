#!/bin/bash

# 🎥 LAN Collaboration Tool - Quick Setup Script
# This script helps you set up the PyQt6 video conferencing app

echo "======================================"
echo "🎥 LAN Collaboration Tool Setup"
echo "======================================"
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 not found. Installing..."
    sudo apt update
    sudo apt install -y python3-pip
fi

# Install system dependencies
echo ""
echo "📦 Installing system dependencies..."
sudo apt update
sudo apt install -y portaudio19-dev python3-pyqt6

# Install Python packages
echo ""
echo "📦 Installing Python packages..."
pip3 install -r requirements.txt

echo ""
echo "======================================"
echo "✅ Setup Complete!"
echo "======================================"
echo ""
echo "To start the server:"
echo "  python3 server.py"
echo ""
echo "To start a client:"
echo "  python3 client.py"
echo ""
echo "Enjoy your colorful conferencing! 🎉"
