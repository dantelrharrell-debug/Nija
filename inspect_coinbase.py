#!/usr/bin/env python3

import sys
import importlib

PACKAGE_NAME = "coinbase_advanced_py"

def main():
    print(f"Python version: {sys.version}")
    try:
        package = importlib.import_module(PACKAGE_NAME)
        print(f"Successfully imported '{PACKAGE_NAME}'\n")
    except ImportError as e:
        print(f"Failed to import '{PACKAGE_NAME}': {e}")
        sys.exit(1)

    # List all top-level attributes and classes
    print(f"Top-level attributes in '{PACKAGE_NAME}':")
    for attr in dir(package):
        print(f" - {attr}")

    # Check submodules
    try:
        
        print("\nTop-level attributes in 'coinbase_advanced_py.advanced':")
        for attr in dir(advanced):
            print(f" - {attr}")
    except ImportError:
        print("\nNo 'advanced' submodule found in 'coinbase_advanced_py'")

if __name__ == "__main__":
    main()
