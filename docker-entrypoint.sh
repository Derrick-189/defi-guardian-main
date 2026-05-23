#!/bin/sh
set -e

# If arguments are provided to the script, execute them (useful for Render "Docker Command" override)
if [ "$#" -gt 0 ]; then
    echo "Executing override command: $@"
    exec "$@"
fi

if [ "$SERVICE_TYPE" = "verification" ]; then
    echo "Starting Verification Server..."
    exec python web_portal/verification_server.py
else
    echo "Starting Web Portal..."
    # Using explicit worker class path to resolve Gunicorn discovery issues
    exec gunicorn --worker-class gunicorn.workers.geventlet.EventletWorker -w 1 --bind 0.0.0.0:${PORT:-10000} wsgi:application
fi
