# start_bot.py - launcher at repo root
# Keeps Railway happy when it tries to run /app/start_bot.py

from app.start_bot_main import main  # import from the app package

if __name__ == "__main__":
    main()
