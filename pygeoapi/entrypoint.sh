#!/bin/bash
set -e

# Start Xvfb on display :99 (safety net for PyQGIS rendering ops)
Xvfb :99 -screen 0 1024x768x24 -ac &
sleep 1

# Launch Gunicorn:
#   --workers 1   : single worker avoids double-fork issues with QgsApplication
#   --threads 4   : handle concurrent HTTP requests (status polling) via threads
#   --timeout 3600: 1-hour timeout for long-running processes
exec gunicorn --bind 0.0.0.0:5000 \
    --workers 1 \
    --threads 4 \
    --timeout 3600 \
    pygeoapi.flask_app:APP
