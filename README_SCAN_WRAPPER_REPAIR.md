# Canonical scan wrapper repair

Runtime marker: `20260712h`.

This repair collapses legacy `run_scan_phase` wrapper chains to one canonical, idempotent wrapper that preserves account-level serialization and the required result contract.
