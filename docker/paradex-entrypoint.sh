#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Save Paradex config
if [[ -n "${PARADEX_CONFIG}" ]]; then
  echo "$PARADEX_CONFIG" | tee /octobot/user/config.json >/dev/null
elif [[ -n "${OCTOBOT_CONFIG}" ]]; then
  echo "$OCTOBOT_CONFIG" | tee /octobot/user/config.json >/dev/null
fi

# Install tentacles on first run (or after volume wipe)
if [ ! -d "/octobot/tentacles/Trading" ]; then
  echo "First run: installing tentacles..."
  SITE=$(python -c "import site; print(site.getsitepackages()[0])")
  # Package tentacles from site-packages into a zip
  cd "$SITE"
  OctoBot tentacles -d tentacles -p /tmp/tentacles.zip
  cd /octobot
  # Install from the zip
  OctoBot tentacles --install --location /tmp/tentacles.zip --all
  rm -f /tmp/tentacles.zip
  echo "Tentacles installed."
fi

# Disable set -e
set +e

# Start Paradex bot (OctoBot engine + Dashboard + Telegram)
python -m paradex_launcher
