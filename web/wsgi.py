"""
WSGI/ASGI wrapper for Gunicorn / Uvicorn.

This file attempts to import your Flask/FastAPI app from common locations:
- main:app
- web.app:app
- web/__init__.py exposing app
- app:app
- If a create_app() factory exists, it will call it with no args.
If none are found, the module raises an ImportError with guidance.
"""
import importlib
import sys
import traceback

CANDIDATES = [
    ("main", "app"),
    ("web.app", "app"),
    ("web", "app"),
    ("app", "app"),
]

app = None
last_exc = None

def try_import(module_name, attr_name):
    try:
        mod = importlib.import_module(module_name)
        if hasattr(mod, attr_name):
            return getattr(mod, attr_name)
        # If module has create_app factory, call it
        if hasattr(mod, "create_app") and callable(getattr(mod, "create_app")):
            return getattr(mod, "create_app")()
    except Exception as e:
        # capture exception to include in final error
        return e
    return None

for module_name, attr_name in CANDIDATES:
    result = try_import(module_name, attr_name)
    if result is None:
        # explicit None means module imported but attribute not found
        last_exc = (module_name, attr_name, "no-attribute")
        continue
    if isinstance(result, Exception):
        last_exc = (module_name, attr_name, result)
        continue
    # success
    app = result
    break

if app is None:
    # Provide helpful debugging output
    msg_lines = [
        "web/wsgi.py: failed to locate WSGI/ASGI 'app' object using common candidates.",
        "Tried the following candidates: " + ", ".join(f"{m}:{a}" for m, a in CANDIDATES),
    ]
    if last_exc:
        module_name, attr_name, exc = last_exc
        if isinstance(exc, Exception):
            tb = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            msg_lines.append(f"Last attempt: import {module_name}; error: {tb}")
        else:
            msg_lines.append(f"Last attempt: import {module_name} succeeded but attribute '{attr_name}' not found.")
    msg = "\n".join(msg_lines)
    raise ImportError(msg)
