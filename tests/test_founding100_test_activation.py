from datetime import datetime, timedelta, timezone
import pytest
from founding100_test_activation import Enrollment, VerifiedFirstFill, ActivationDenied, checkout_allowed, activate_test_only

NOW = datetime(2026, 11, 23, 20, tzinfo=timezone.utc)
class Ledger:
    def __init__(self): self.claimed=set(); self.active={}
    def claim_once(self, member_id, execution_id, starts_at, ends_at):
        if member_id in self.claimed: return False
        self.claimed.add(member_id); return True
    def get_activation(self, member_id): return self.active.get(member_id)
    def record_activation(self, member_id, subscription_id): self.active[member_id]=subscription_id
class Provider:
    mode="test"
    def __init__(self): self.calls=[]
    def create_subscription(self, **kwargs):
        self.calls.append(kwargs); return "sub_test_1"
def fixtures():
    e=Enrollment("member-1","founding100",None,NOW-timedelta(days=2),NOW+timedelta(days=2))
    f=VerifiedFirstFill("member-1","execution-1",NOW-timedelta(hours=1),True,True)
    return e,f,Ledger(),Provider()
def test_checkout_guard():
    e,*_=fixtures()
    assert not checkout_allowed(e)
    assert checkout_allowed(Enrollment("m","course",None,None,None))
def test_first_fill_activates_once():
    e,f,l,p=fixtures()
    assert activate_test_only(e,f,l,p,now=NOW)=="sub_test_1"
    assert activate_test_only(e,f,l,p,now=NOW)=="sub_test_1"
    assert len(p.calls)==1
    assert p.calls[0]["amount_cents"]==5000
    assert p.calls[0]["trial_end"]==f.executed_at+timedelta(days=14)
@pytest.mark.parametrize("change",[
    ("existing_subscription_id","sub_live_existing"),
    ("canceled",True),
    ("consent_expires_at",NOW-timedelta(seconds=1)),
])
def test_denied_enrollment(change):
    from dataclasses import replace
    e,f,l,p=fixtures()
    with pytest.raises(ActivationDenied):
        activate_test_only(replace(e,**dict([change])),f,l,p,now=NOW)
    assert not p.calls
def test_no_paper_or_mismatched_fill():
    from dataclasses import replace
    e,f,l,p=fixtures()
    for invalid in (replace(f,live=False),replace(f,filled=False),replace(f,member_id="other")):
        with pytest.raises(ActivationDenied): activate_test_only(e,invalid,l,p,now=NOW)
    assert not p.calls
def test_live_mode_denied():
    e,f,l,p=fixtures(); p.mode="live"
    with pytest.raises(ActivationDenied): activate_test_only(e,f,l,p,now=NOW)
    assert not p.calls
def test_old_fill_denied():
    from dataclasses import replace
    e,f,l,p=fixtures()
    with pytest.raises(ActivationDenied):
        activate_test_only(e,replace(f,executed_at=NOW-timedelta(days=15)),l,p,now=NOW)
