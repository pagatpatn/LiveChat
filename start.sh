#!/bin/bash
# Install Chromium and driver in Railway container
apt-get update
apt-get install -y chromium chromium-driver

# Run Python app
python main.py
