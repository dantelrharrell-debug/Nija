import sys
import os

# Add the app folder to the Python module search path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

# Now we can import start_bot_main
from start_bot_main import main

if __name__ == "__main__":
    main()
