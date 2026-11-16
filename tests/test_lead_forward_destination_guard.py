"""Fail-closed lead-forward destination tests. No network, leads, or mail sent."""
import json
import urllib.error

import pytest

import render_lead_intake as intake

VALID_HOOK = "https://hooks.zapier.com/hooks/catch/28448233/synthetic-QA_secret-1/"


@pytest.mark.parametrize("destination", [
    "http://hooks.zapier.com/hooks/catch/28448233/synthetic-QA_secret-1/",
    "https://hooks.zapier.com.evil.example/hooks/catch/28448233/token/",
    "https://hooks.zapier.com@evil.example/hooks/catch/28448233/token/",
    "https://hooks.zapier.com:443/hooks/catch/28448233/token/",
    "https://hooks.zapier.com/other/endpoint",
    "https://hooks.zapier.com/hooks/catch/not-an-id/token/",
    "https://hooks.zapier.com/hooks/catch/28448233/token/?foo=bar",
    "https://hooks.zapier.com/hooks/catch/28448233/token/#fragment",
    "https://hooks.zapier.com/hooks/catch/28448233/token%2fother/",
    "https://hooks.zapier.com/hooks/catch/28448233/token/extra",
    " https://hooks.zapier.com/hooks/catch/28448233/token/",
    "https://hooks.zapier.com/hooks/catch/28448233/token/\n",
])
def test_unapproved_forward_never_opens_network(monkeypatch, destination):
    monkeypatch.setenv("NIJA_LEAD_FORWARD_URL", destination)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Invalid forwarding configuration sent a network request")
    monkeypatch.setattr(intake.urllib.request, "build_opener", forbidden)

    with pytest.raises(OSError, match="not an approved Zapier Catch Hook"):
        intake._forward({"email": "synthetic@example.com"})


def test_blank_forwarding_does_not_send(monkeypatch):
    monkeypatch.delenv("NIJA_LEAD_FORWARD_URL", raising=False)
    monkeypatch.setattr(
        intake.urllib.request, "build_opener",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected network"))
    )
    assert intake._forward({"email": "synthetic@example.com"}) is False


def test_approved_hook_emits_one_unmodified_post(monkeypatch):
    monkeypatch.setenv("NIJA_LEAD_FORWARD_URL", VALID_HOOK)
    monkeypatch.delenv("NIJA_LEAD_FORWARD_BEARER", raising=False)
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, max_bytes):
            assert max_bytes == 4096
            return b'{"ok":true}'

    class Opener:
        def open(self, req, timeout):
            assert timeout == 10.0
            calls.append(req)
            return Response()

    def make_opener(handler):
        assert isinstance(handler, intake._NoLeadForwardRedirect)
        return Opener()

    monkeypatch.setattr(intake.urllib.request, "build_opener", make_opener)
    synthetic = {"email": "synthetic@example.com", "event_id": "QA-1",
                 "send_acknowledgment": False}
    assert intake._forward(synthetic) is True
    assert len(calls) == 1
    req = calls[0]
    assert req.full_url == VALID_HOOK
    assert req.get_method() == "POST"
    assert json.loads(req.data) == synthetic


def test_redirects_never_forward_payload():
    guard = intake._NoLeadForwardRedirect()
    assert guard.redirect_request(
        None, None, 307, "redirect", {}, "https://untrusted.example/new"
    ) is None


def test_provider_error_does_not_echo_hook_url_or_customer_data(monkeypatch):
    monkeypatch.setenv("NIJA_LEAD_FORWARD_URL", VALID_HOOK)
    class Opener:
        def open(self, req, timeout):
            raise urllib.error.HTTPError(req.full_url, 302, "redirect", {}, None)
    monkeypatch.setattr(intake.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(OSError) as exc:
        intake._forward({"email": "synthetic@example.com"})
    assert "Unable to forward canonical lead payload" in str(exc.value)
    assert VALID_HOOK not in str(exc.value)
    assert "synthetic@example.com" not in str(exc.value)
