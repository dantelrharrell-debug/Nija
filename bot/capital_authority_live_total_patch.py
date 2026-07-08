from __future__ import annotations


def install_import_hook() -> None:
    try:
        from bot.capital_authority_live_total_v2_patch import install_import_hook as _capital_install  # type: ignore
    except Exception:
        from capital_authority_live_total_v2_patch import install_import_hook as _capital_install  # type: ignore
    _capital_install()
    try:
        from bot.execution_route_integrity_import_guard_patch import install_import_hook as _route_install  # type: ignore
    except Exception:
        try:
            from execution_route_integrity_import_guard_patch import install_import_hook as _route_install  # type: ignore
        except Exception:
            _route_install = None  # type: ignore
    if callable(_route_install):
        _route_install()


def install() -> None:
    install_import_hook()
