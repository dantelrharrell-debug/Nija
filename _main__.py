import time
from app.start_bot_main import start_bot_main  # adjust if your function name differs

if __name__ == "__main__":
    print("Nija bot is starting...")
    
    try:
        start_bot_main()
    except Exception as e:
        print(f"Error starting bot: {e}")

    print("Nija bot is now running...")

    # Keep the container alive (heartbeat)
    while True:
        time.sleep(60)
