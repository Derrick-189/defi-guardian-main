
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.abspath('.'))

from desktop_app import flask_app

if __name__ == "__main__":
    print("Starting Desktop App Web Preview on port 5005...")
    print("Registered routes:")
    for rule in flask_app.url_map.iter_rules():
        print(f"  {rule}")
    # Reverting to port 5005 as it's the standard for the app
    flask_app.run(port=5005, debug=False, threaded=True)
