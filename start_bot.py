# start_bot.py  <-- must be at repo root so Docker COPY can find it
from app.start_bot_main import main

if __name__ == "__main__":
    main()
