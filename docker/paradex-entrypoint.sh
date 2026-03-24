#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Save Paradex config
if [[ -n "${PARADEX_CONFIG}" ]]; then
  echo "$PARADEX_CONFIG" | tee /octobot/user/config.json >/dev/null
# Fallback to OCTOBOT_CONFIG for backwards compatibility
elif [[ -n "${OCTOBOT_CONFIG}" ]]; then
  echo "$OCTOBOT_CONFIG" | tee /octobot/user/config.json >/dev/null
fi

# Disable set -e
set +e

# Start Paradex trading bot
OctoBot
