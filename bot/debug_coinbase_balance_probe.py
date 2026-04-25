#!/usr/bin/env python3
"""One-shot Coinbase balance isolation probe.

This script intentionally triggers CoinbaseBroker.get_account_balance(), which now logs:
- === RAW BALANCES === ...
- === USD AVAILABLE === ...

It will hard-fail with AssertionError("NO USABLE FUNDS DETECTED") when usable USD is zero.
"""

from __future__ import annotations

import sys

from bot.broker_manager import CoinbaseBroker

try:
    from bot.multi_account_broker_manager import multi_account_broker_manager
except Exception:
    multi_account_broker_manager = None


def _extract_accounts(accounts_resp):
    return getattr(accounts_resp, "accounts", []) or (
        accounts_resp.get("accounts", []) if isinstance(accounts_resp, dict) else []
    )


def _sum_usd_available(accounts):
    usd_available = 0.0
    for acc in accounts:
        if isinstance(acc, dict):
            currency = acc.get("currency")
            available_val = (acc.get("available_balance") or {}).get("value")
        else:
            currency = getattr(acc, "currency", None)
            available_val = getattr(getattr(acc, "available_balance", None), "value", None)

        if currency == "USD":
            try:
                usd_available += float(available_val or 0.0)
            except Exception:
                continue
    return usd_available


def main() -> int:
    if multi_account_broker_manager is not None:
        try:
            if hasattr(multi_account_broker_manager, "get_aggregated_balance_breakdown"):
                agg = multi_account_broker_manager.get_aggregated_balance_breakdown(
                    include_all_subaccounts=True
                )
                print(f"aggregated_breakdown={agg}")
            if hasattr(multi_account_broker_manager, "get_platform_total_balance"):
                agg_total = multi_account_broker_manager.get_platform_total_balance(
                    include_all_subaccounts=True
                )
                print(f"aggregated_total_balance={agg_total}")
        except Exception as exc:
            print(f"aggregated_probe_exception={type(exc).__name__}: {exc}")

    broker = CoinbaseBroker()

    connected = broker.connect()
    print(f"connected={connected}")
    if not connected:
        print("Coinbase connection failed")
        return 1

    try:
        if hasattr(broker, "client") and broker.client is not None and hasattr(broker.client, "get_accounts"):
            accounts_resp = broker.client.get_accounts()
            accounts = _extract_accounts(accounts_resp)
            usd_available = _sum_usd_available(accounts)
            print(f"accounts_count={len(accounts)}")
            print(f"usd_available_from_accounts={usd_available}")

        balance = broker.get_account_balance(verbose=True)
        print(f"balance={balance}")
        return 0
    except AssertionError as exc:
        print(f"assertion={exc}")
        print("diagnostic=NO_USABLE_FUNDS_DETECTED")
        print("hint=verify Advanced Trade account mapping and transfer funds from Consumer wallet if needed")
        raise
    except Exception as exc:
        print(f"exception={type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
