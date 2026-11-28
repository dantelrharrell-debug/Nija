import logging

from alpha_onboarding import AlphaOnboardingSystem


def test_invitation_lifecycle_keeps_registration_code_out_of_logs(caplog):
    onboarding = AlphaOnboardingSystem()

    with caplog.at_level(logging.INFO, logger="alpha_onboarding"):
        invitation = onboarding.generate_invitation_code("alice@example.com")
        assert onboarding.validate_invitation_code(invitation.code)[0]
        assert onboarding.revoke_invitation(invitation.code)[0]

    assert "Generated onboarding invitation" in caplog.text
    assert "Revoked onboarding invitation" in caplog.text
    assert invitation.code not in caplog.text
    assert invitation.email not in caplog.text
