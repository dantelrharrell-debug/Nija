bind = "0.0.0.0:8080"
workers = 2
worker_class = "gthread"
threads = 1
timeout = 120
loglevel = "debug"
capture_output = True

def post_worker_init(worker):
    from app import init_bot
    init_bot()
