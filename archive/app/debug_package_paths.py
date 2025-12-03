# /app/debug_package_paths.py
import importlib.util, json, sys, pkgutil
candidates = [
  "coinbase_advanced.client",
  "coinbase_advanced_py.client",
  "coinbase_advanced_py",
  "coinbase_advanced",
  "coinbaseadvanced.client",
  "coinbaseadvanced",
]
out = {}
for name in candidates:
    try:
        spec = importlib.util.find_spec(name)
        if spec is None:
            out[name] = None
        else:
            out[name] = {
                "name": spec.name,
                "origin": getattr(spec, "origin", None),
                "has_loader": bool(spec.loader),
                "loader_type": type(spec.loader).__name__ if spec.loader else None,
            }
    except Exception as e:
        out[name] = f"error: {e}"

out["sys_path_sample"] = sys.path[:20]
out["site_packages_sample_names"] = [m.name for m in pkgutil.iter_modules()][:200]

print(json.dumps(out, indent=2))
