# Scan-owner stability fix

The scan-owner convergence watchdog previously reinstalled a wrapper that had just been removed by `reentrant_scan_owner_repair.py`, creating a five-second patch/remove loop.

The repair now guards the convergence module's `_patch_core` function. Canonical scan methods marked as repaired are left untouched, while newly loaded core-loop classes are repaired once and then remain stable.
