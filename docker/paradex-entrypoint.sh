#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Save Paradex config
if [[ -n "${PARADEX_CONFIG}" ]]; then
  echo "$PARADEX_CONFIG" | tee /octobot/user/config.json >/dev/null
elif [[ -n "${OCTOBOT_CONFIG}" ]]; then
  echo "$OCTOBOT_CONFIG" | tee /octobot/user/config.json >/dev/null
fi

# Disable set -e
set +e

# Start Paradex bot (OctoBot engine + Dashboard + Telegram)
python -m paradex_launcher
