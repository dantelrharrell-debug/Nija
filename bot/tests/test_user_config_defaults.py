from config.individual_user_loader import IndividualUserConfig
from config.user_loader import UserConfig


def test_json_user_config_defaults_to_independent_no_copy_mode():
    user = UserConfig.from_dict(
        {
            "user_id": "new_kraken_user",
            "name": "New Kraken User",
            "account_type": "retail",
            "broker_type": "kraken",
        }
    )

    assert user.independent_trading is True
    assert user.copy_from_platform is False


def test_individual_user_config_defaults_to_independent_no_copy_mode():
    user = IndividualUserConfig.from_dict(
        "new_kraken_user",
        {
            "name": "New Kraken User",
            "broker": "kraken",
        },
    )

    assert user.independent_trading is True
    assert user.copy_from_platform is False
