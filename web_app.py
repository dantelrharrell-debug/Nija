# web_app.py
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import importlib
import inspect
import asyncio
import logging
import sys
from typing import Any

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("web_app")

app = FastAPI(title="Webhook wrapper")

# Try to import an ASGI app directly from tv_webhook_listener if it exists.
try:
    tv = importlib.import_module("tv_webhook_listener")
    # If tv_webhook_listener defines an 'app' attribute and it is ASGI-compatible, use it
    candidate_app = getattr(tv, "app", None)
    if candidate_app is not None:
        log.info("Using tv_webhook_listener.app as the ASGI app.")
        # expose tv's app under this process (mount)
        # FastAPI's include_router expects a Starlette/FastAPI router, but candidate_app
        # may itself be a FastAPI app. If so, delegate by mounting.
        if hasattr(candidate_app, "router"):
            from fastapi.middleware.wsgi import WSGIMiddleware  # fallback, but shouldn't be needed
            # mount the candidate app at root
            app.mount("/", candidate_app)
        else:
            # fallback: still mount by wrapping — keep the existing app but keep wrapper endpoints
            log.info("candidate_app found but not a FastAPI instance; continuing with wrapper endpoints.")
    else:
        log.info("tv_webhook_listener module found but no 'app' attribute; using wrapper endpoints.")
except Exception as e:
    log.info(f"tv_webhook_listener import failed or not present: {e}")

# Generic wrapper POST endpoint for webhooks.
# It will call, if present in tv_webhook_listener module, one of:
# - handle_webhook(request, body)
# - process_webhook(request, body)
# - on_webhook(request, body)
# If these don't exist, it returns 404 with a helpful message.

@app.post("/webhook")
async def webhook_entry(request: Request):
    body = await request.body()
    # Try to call a handler in tv_webhook_listener
    try:
        tv = importlib.import_module("tv_webhook_listener")
    except Exception as e:
        log.error(f"tv_webhook_listener could not be imported: {e}")
        return JSONResponse({"error": "tv_webhook_listener module not found", "details": str(e)}, status_code=500)

    # Candidate handler names in order of preference
    handler_names = ["handle_webhook", "process_webhook", "on_webhook", "handle_request"]

    for name in handler_names:
        handler = getattr(tv, name, None)
        if handler:
            log.info(f"Invoking handler {name} in tv_webhook_listener")
            try:
                # If handler is async
                if inspect.iscoroutinefunction(handler):
                    result = await handler(request, body)
                else:
                    # call sync function in threadpool to avoid blocking
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: handler(request, body))
                # If result is a FastAPI Response or dict, return appropriately
                if isinstance(result, Response):
                    return result
                if isinstance(result, dict):
                    return JSONResponse(result)
                # else just return text
                return Response(str(result), media_type="text/plain")
            except Exception as e:
                log.exception(f"Error running handler {name}: {e}")
                return JSONResponse({"error": "handler exception", "details": str(e)}, status_code=500)

    # No handler found
    log.warning("No webhook handler function found in tv_webhook_listener.")
    return JSONResponse({
        "error": "No webhook handler found in tv_webhook_listener",
        "expected_handlers": handler_names,
        "note": "If your tv_webhook_listener defines an ASGI app variable named 'app', it will be used instead."
    }, status_code=404)


@app.get("/health")
async def health():
    return {"status": "ok"}
