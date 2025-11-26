# add this to web/wsgi.py (or app.py) near other routes
import pkgutil
from flask import jsonify

@app.route("/debug/modules")
def debug_modules():
    """
    Return a small JSON list of top-level modules discovered by pkgutil.iter_modules().
    Not exhaustive but helpful for debugging install/import issues.
    """
    names = sorted([m.name for m in pkgutil.iter_modules()])
    # return only a short list to avoid massive output
    short = [n for n in names if n.startswith('coin') or n.startswith('coinbase')][:200]
    return jsonify({
        "found_matches_sample": short,
        "count_top_level": len(names)
    })
