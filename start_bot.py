import sys
import os

# Add app folder to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

# Now import from the app folder
from start_bot_main import main

if __name__ == "__main__":
    main()
