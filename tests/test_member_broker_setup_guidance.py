from member_broker_setup_guidance import broker_setup_view

def view(**kw):
    p=dict(authenticated=True, entitled=True, supported=("kraken", "coinbase"),
           secure_credential_backend_ready=True, customer_selected_broker="kraken")
    p.update(kw)
    return broker_setup_view(**p)

def test_no_login_or_entitlement_never_collects_keys():
    assert not view(authenticated=False).show_secret_entry
    assert not view(entitled=False).show_secret_entry

def test_no_unverified_credential_backend_collects_keys():
    d=view(secure_credential_backend_ready=False)
    assert d.stage=="secure_connection_unavailable"
    assert not d.show_secret_entry

def test_unsupported_broker_rejected():
    assert view(customer_selected_broker="okx").stage=="unsupported_broker"

def test_broker_selection_has_no_secret_fields():
    assert not view(customer_selected_broker="").show_secret_entry

def test_verified_connection_is_still_not_live_trading_authorization():
    assert view(broker_account_verified=True).allow_live_trading is False

def test_credential_entry_only_for_proven_authenticated_flow():
    d=view()
    assert d.show_secret_entry and not d.allow_live_trading
    assert "not generally available for self-service" in d.message
    assert "limited to eligible accounts" in d.message
