bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
graceful_timeout = 120
loglevel = "debug"
capture_output = True

def post_worker_init(worker):
    import sys
    from app import nija_bot
    print("post_worker_init: starting NIJA bot", file=sys.stderr)
    nija_bot.start_bot()
