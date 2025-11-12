import sys
import os

# Add `app` folder to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

# Now import the main function
from start_bot_main import main

if __name__ == "__main__":
    main()
