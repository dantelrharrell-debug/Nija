import sys

def _print(pkg_name):
    try:
        m = __import__(pkg_name)
        v = getattr(m, "__version__", "<unknown>")
        print(f"{pkg_name} version: {v}")
    except Exception as e:
        print(f"{pkg_name} import error: {e}")

def main():
    print("Python:", sys.version.splitlines()[0])
    try:
        import jwt
        print("PyJWT version:", getattr(jwt, "__version__", "<unknown>"))
        try:
            algos = []
            if hasattr(jwt, "api_jws") and hasattr(jwt.api_jws, "_algorithms"):
                algos = list(jwt.api_jws._algorithms.keys())
            elif hasattr(jwt, "algorithms") and hasattr(jwt.algorithms, "get_default_algorithms"):
                algos = list(jwt.algorithms.get_default_algorithms().keys())
            print("Registered JWT algorithms:", algos)
        except Exception as e:
            print("Could not enumerate jwt algorithms:", e)
    except Exception as e:
        print("PyJWT import error:", e)
    _print("cryptography")
    _print("ecdsa")

if __name__ == '__main__':
    main()
