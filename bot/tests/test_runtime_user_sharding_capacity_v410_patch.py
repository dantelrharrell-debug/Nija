from types import SimpleNamespace

from bot import runtime_user_sharding_capacity_v410_patch as patch


def _user(user_id: str):
    return SimpleNamespace(user_id=user_id)


def test_shard_assignment_is_stable():
    first = patch.shard_for_user("user-123", 5)
    second = patch.shard_for_user("user-123", 5)
    assert first == second
    assert 0 <= first < 5


def test_all_users_land_on_exactly_one_shard():
    users = [f"user-{i}" for i in range(250)]
    for user_id in users:
        matches = [idx for idx in range(5) if patch.shard_for_user(user_id, 5) == idx]
        assert len(matches) == 1


def test_capacity_selection_is_deterministic(monkeypatch):
    monkeypatch.setenv("NIJA_USER_SHARD_COUNT", "1")
    monkeypatch.setenv("NIJA_USER_SHARD_INDEX", "0")
    monkeypatch.setenv("NIJA_MAX_USERS_PER_SHARD", "25")
    users = [_user(f"user-{i:03d}") for i in range(40)]
    admitted, overflow, meta = patch._select_users(reversed(users))
    assert len(admitted) == 25
    assert len(overflow) == 15
    assert meta["assigned"] == 40
    assert [u.user_id for u in admitted] == [f"user-{i:03d}" for i in range(25)]


def test_five_shards_cover_125_without_overlap(monkeypatch):
    users = [_user(f"user-{i:03d}") for i in range(125)]
    seen = set()
    for idx in range(5):
        monkeypatch.setenv("NIJA_USER_SHARD_COUNT", "5")
        monkeypatch.setenv("NIJA_USER_SHARD_INDEX", str(idx))
        monkeypatch.setenv("NIJA_MAX_USERS_PER_SHARD", "40")
        admitted, overflow, _meta = patch._select_users(users)
        assert not overflow
        ids = {u.user_id for u in admitted}
        assert not (seen & ids)
        seen |= ids
    assert seen == {u.user_id for u in users}
