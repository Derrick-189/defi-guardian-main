import eventlet
eventlet.monkey_patch()

import os
import sys

# Add the project root and web_portal to sys.path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, 'web_portal'))

from web_portal.app import app as application

if __name__ == "__main__":
    from web_portal.app import socketio
    socketio.run(application)
