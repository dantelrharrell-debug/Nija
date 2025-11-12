import sys
import os

# Add the `app` folder to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "app"))

# Now import your bot
from start_bot_main import main

if __name__ == "__main__":
    main()
