#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Save Paradex config — validate JSON before writing
if [[ -n "${PARADEX_CONFIG}" ]]; then
  echo "${PARADEX_CONFIG}" | python -m json.tool > /dev/null 2>&1 \
    || { echo "ERROR: PARADEX_CONFIG is not valid JSON"; exit 1; }
  printf '%s' "${PARADEX_CONFIG}" > /octobot/user/config.json
elif [[ -n "${OCTOBOT_CONFIG}" ]]; then
  echo "${OCTOBOT_CONFIG}" | python -m json.tool > /dev/null 2>&1 \
    || { echo "ERROR: OCTOBOT_CONFIG is not valid JSON"; exit 1; }
  printf '%s' "${OCTOBOT_CONFIG}" > /octobot/user/config.json
fi

# Install tentacles on first run (or after volume wipe)
if [ ! -d "/octobot/tentacles/Trading" ]; then
  echo "First run: installing tentacles..."
  SITE=$(python -c "import site; print(site.getsitepackages()[0])")
  # Package tentacles from site-packages into a zip
  # Run from /octobot so OctoBot can write logs/ here (owned by octobot user)
  OctoBot tentacles -d "$SITE/tentacles" -p /tmp/any_platform.zip
  OctoBot tentacles --install --location /tmp/any_platform.zip --all
  rm -f /tmp/any_platform.zip
  echo "Tentacles installed."
fi

# Disable set -e for launcher (handles its own errors)
set +e

# Start Paradex bot (OctoBot engine + Dashboard + Telegram)
python -m paradex_launcher
