from decimal import Decimal

from commercial_offer_store import CommercialOfferStore


def test_founding_beta_assignments_are_persisted_and_price_locked(tmp_path):
    store = CommercialOfferStore(str(tmp_path / "users.db"))

    first = store.assign_beta_offer("user_1")
    again = store.assign_beta_offer("user_1")

    assert first == again
    assert first.offer_code == "founding_beta"
    assert first.price_usd == Decimal("50.00")
    assert first.trial_days == 14
    assert first.cohort_position == 1
    assert first.to_dict()["price_locked"] is True


def test_exactly_first_100_users_receive_founding_beta(tmp_path):
    store = CommercialOfferStore(str(tmp_path / "users.db"))

    assignments = [store.assign_beta_offer(f"user_{number}") for number in range(1, 101)]

    assert store.founding_beta_claimed_count() == 100
    assert assignments[0].cohort_position == 1
    assert assignments[-1].cohort_position == 100
    assert all(item.offer_code == "founding_beta" for item in assignments)
    assert all(item.price_usd == Decimal("50.00") for item in assignments)
    assert all(item.trial_days == 14 for item in assignments)


def test_user_101_gets_standard_beta_without_repricing_first_100(tmp_path):
    store = CommercialOfferStore(str(tmp_path / "users.db"))
    first = store.assign_beta_offer("user_1")
    for number in range(2, 101):
        store.assign_beta_offer(f"user_{number}")

    user_101 = store.assign_beta_offer("user_101")
    first_after = store.get_assignment("user_1")

    assert user_101.offer_code == "standard_beta"
    assert user_101.price_usd == Decimal("75.00")
    assert user_101.trial_days == 0
    assert user_101.cohort_position is None

    assert first_after == first
    assert first_after.price_usd == Decimal("50.00")
    assert first_after.trial_days == 14
