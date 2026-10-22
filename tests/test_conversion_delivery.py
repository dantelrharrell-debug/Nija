"""No network calls: all delivery tests use a fake transport."""
import pytest

from analytics.conversion_delivery import DeliveryDisabled, deliver_ga4


class FakeTransport:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        class Response:
            status_code = 204
            def raise_for_status(self):
                pass
        return Response()


def kwargs_for(sender):
    return dict(client_id="123456789.123456789", measurement_id="G-ABCDE12345",
                api_secret="test-only-secret", transport=sender)


def test_delivery_disabled_by_default():
    sender = FakeTransport()
    with pytest.raises(DeliveryDisabled):
        deliver_ga4({"event_name": "nija_verified_lead", "parameters": {}},
                    **kwargs_for(sender))
    assert sender.calls == []


def test_course_payload_excludes_pii():
    sender = FakeTransport()
    event = {"event_name": "nija_verified_course_purchase",
             "parameters": {"transaction_id": "cs_test_123", "currency": "USD",
                            "value": 99.0, "email": "private@example.com"}}
    assert deliver_ga4(event, enabled=True, **kwargs_for(sender))
    assert len(sender.calls) == 1
    url, request = sender.calls[0]
    assert url == "https://www.google-analytics.com/mp/collect"
    assert "private@example.com" not in str(request["json"])
    assert request["json"]["events"][0]["params"]["transaction_id"] == "cs_test_123"


def test_rejects_invalid_attribution_and_event():
    sender = FakeTransport()
    event = {"event_name": "nija_verified_lead", "parameters": {}}
    with pytest.raises(ValueError):
        deliver_ga4(event, enabled=True, client_id="untrusted", measurement_id="G-ABCDE12345",
                    api_secret="test", transport=sender)
    with pytest.raises(ValueError):
        deliver_ga4({"event_name": "page_view", "parameters": {}}, enabled=True, **kwargs_for(sender))
    assert sender.calls == []


def test_http_failure_does_not_report_delivery():
    sender = FakeTransport()
    class Rejected:
        status_code = 403
        def raise_for_status(self):
            raise RuntimeError("provider_rejected")
    sender.post = lambda *args, **kwargs: Rejected()
    with pytest.raises(RuntimeError, match="provider_rejected"):
        deliver_ga4({"event_name": "nija_verified_lead", "parameters": {}},
                    enabled=True, **kwargs_for(sender))


def test_invalid_course_value_never_sends():
    sender = FakeTransport()
    with pytest.raises(ValueError, match="invalid_course_value"):
        deliver_ga4({"event_name": "nija_verified_course_purchase",
                     "parameters": {"transaction_id": "cs_123",
                                    "currency": "USD", "value": 0}},
                    enabled=True, **kwargs_for(sender))
    assert sender.calls == []


def test_unsupported_event_never_sends():
    sender = FakeTransport()
    with pytest.raises(ValueError, match="unsupported_conversion_event"):
        deliver_ga4({"event_name": "purchase", "parameters": {}},
                    enabled=True, **kwargs_for(sender))
    assert sender.calls == []
