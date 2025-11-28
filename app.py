def get_startup_info():
    return {
        "startups": [
            {
                "container_start": "2025-11-28T21:47:23.000000000Z",
                "gunicorn": {
                    "workers": 2,
                    "worker_class": "gthread",
                    "threads": 2,
                    "bind": "0.0.0.0:8080",
                    "loglevel": "debug",
                    "capture_output": True,
                    "worker_connections": 1000,
                    "limit_request_fields": 100,
                    "limit_request_field_size": 8190,
                    "limit_request_line": 4094,
                    "timeout": 120,
                    "graceful_timeout": 30,
                    "keepalive": 2,
                    "reload": False,
                    "preload_app": False,
                    "reuse_port": False,
                    "daemon": False,
                    "chdir": "/app"
                },
                "optional_modules_skipped": [
                    "nija_client.optional_app_module1",
                    "nija_client.optional_app_module2"
                ]
            },
            {
                "container_start": "2025-11-28T22:03:34.000000000Z",
                "gunicorn": {
                    "workers": 2,
                    "worker_class": "gthread",
                    "threads": 2,
                    "bind": "0.0.0.0:8080",
                    "loglevel": "debug",
                    "capture_output": True,
                    "worker_connections": 1000,
                    "limit_request_fields": 100,
                    "limit_request_field_size": 8190,
                    "limit_request_line": 4094,
                    "timeout": 120,
                    "graceful_timeout": 30,
                    "keepalive": 2,
                    "reload": False,
                    "preload_app": False,
                    "reuse_port": False,
                    "daemon": False,
                    "chdir": "/app"
                },
                "optional_modules_skipped": [
                    "nija_client.optional_app_module1",
                    "nija_client.optional_app_module2"
                ]
            }
        ]
    }
