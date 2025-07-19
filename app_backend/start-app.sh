#!/usr/bin/env bash

export PORT=${PORT:-"8080"}
DEV_MODE=${DEV_MODE:-false}
LOG_LEVEL="info"
EXTRA_OPTS=(--proxy-headers)

if [ "${DEV_MODE,,}" = "true" ]; then
  EXTRA_OPTS+=("--reload")
fi

# Add vendor directory to Python path for vendored packages
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}$(pwd)/vendor:$(pwd)/app_backend/vendor:$(pwd)/utils/vendor"
echo "PYTHONPATH set to: $PYTHONPATH"

python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --log-level $LOG_LEVEL "${EXTRA_OPTS[@]}"
