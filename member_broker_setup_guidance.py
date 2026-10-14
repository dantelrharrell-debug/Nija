"""Safe member-facing brokerage setup instructions (no secret processing).

This is a decision/display helper only. It cannot save API credentials,
authorize trades, or infer that a broker is connected.
"""
from dataclasses import dataclass


BROKERS = ("kraken", "coinbase", "alpaca", "okx")


@dataclass(frozen=True)
class BrokerSetupView:
    stage: str
    message: str
    supported_choices: tuple[str, ...]
    show_secret_entry: bool
    allow_live_trading: bool


def broker_setup_view(*, authenticated: bool, entitled: bool,
                      supported: tuple[str, ...] = (),
                      secure_credential_backend_ready: bool = False,
                      customer_selected_broker: str = "",
                      broker_account_verified: bool = False) -> BrokerSetupView:
    """Never expose a credential collection UI when its backend is unverified."""
    if not authenticated:
        return BrokerSetupView("login_required", "Sign in to continue.", (), False, False)
    if not entitled:
        return BrokerSetupView("membership_pending", "Membership verification is pending. Do not pay again if you already have an active trial.", (), False, False)
    choices = tuple(b for b in BROKERS if b in supported)
    if not choices:
        return BrokerSetupView("unavailable", "Brokerage setup is temporarily unavailable. Education and paper trading remain available.", (), False, False)
    broker = customer_selected_broker.strip().lower()
    if not broker:
        return BrokerSetupView("select_broker", "Select your own brokerage to review its connection requirements. This does not enable live trading.", choices, False, False)
    if broker not in choices:
        return BrokerSetupView("unsupported_broker", "That brokerage is not available for secure connection. Choose a listed option.", choices, False, False)
    if not secure_credential_backend_ready:
        return BrokerSetupView("secure_connection_unavailable", "Secure credential entry is not yet verified. Do not send API keys through email, chat, or support.", choices, False, False)
    if not broker_account_verified:
        return BrokerSetupView("connect_in_portal", "Connect only through the authenticated, encrypted NIJA brokerage connection flow. Disable withdrawal permission. Connection alone does not enable live trading.", choices, True, False)
    return BrokerSetupView("connected_pending_safety", "Your brokerage connection is verified. Trading remains disabled until account-specific risk controls, protective exits, reconciliation, and explicit live-trading consent are verified.", choices, False, False)
