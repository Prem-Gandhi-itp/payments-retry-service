import logging

import pytest

import retry_worker
from retry_worker import (
    BACKOFF_BASE,
    MAX_RETRIES,
    GatewayTimeoutError,
    PaymentEvent,
    call_payment_gateway,
    log_retry_status,
    process_payment_event,
)


@pytest.fixture
def event():
    return PaymentEvent("EVT-001", 99.99, "USD")


class TestConstants:
    def test_retry_configuration(self):
        assert MAX_RETRIES == 3
        assert BACKOFF_BASE == 2


class TestPaymentEvent:
    def test_initial_state(self, event):
        assert event.event_id == "EVT-001"
        assert event.amount == 99.99
        assert event.currency == "USD"
        assert event.status == "PENDING"
        assert event.retry_count == 0

    def test_events_do_not_share_state(self):
        first = PaymentEvent("EVT-A", 1.0, "USD")
        second = PaymentEvent("EVT-B", 2.0, "EUR")

        first.status = "SUCCESS"
        first.retry_count = 2

        assert second.status == "PENDING"
        assert second.retry_count == 0


class TestCallPaymentGateway:
    def test_raises_gateway_timeout(self, event):
        with pytest.raises(GatewayTimeoutError) as excinfo:
            call_payment_gateway(event)

        assert event.event_id in str(excinfo.value)

    def test_gateway_timeout_is_an_exception(self):
        assert issubclass(GatewayTimeoutError, Exception)


class TestProcessPaymentEvent:
    def test_success_path(self, event, monkeypatch):
        monkeypatch.setattr(
            retry_worker, "call_payment_gateway", lambda e: {"id": "auth-1"}
        )

        assert process_payment_event(event) == "SUCCESS"
        assert event.status == "SUCCESS"
        assert event.retry_count == 0

    def test_non_retryable_error_marks_event_failed(self, event, monkeypatch):
        def boom(_):
            raise ValueError("card declined")

        monkeypatch.setattr(retry_worker, "call_payment_gateway", boom)

        assert process_payment_event(event) == "FAILED"
        assert event.status == "FAILED"

    def test_failure_is_logged_with_event_id(self, event, monkeypatch, caplog):
        def boom(_):
            raise ValueError("card declined")

        monkeypatch.setattr(retry_worker, "call_payment_gateway", boom)

        with caplog.at_level(logging.ERROR, logger=retry_worker.__name__):
            process_payment_event(event)

        assert event.event_id in caplog.text

    @pytest.mark.xfail(
        reason="Known bug: GatewayTimeoutError is swallowed by the generic "
        "except block, so no retry is attempted.",
        strict=True,
    )
    def test_gateway_timeout_is_retried(self, event, monkeypatch):
        attempts = {"count": 0}

        def flaky(_):
            attempts["count"] += 1
            if attempts["count"] <= 2:
                raise GatewayTimeoutError("timeout")
            return {"id": "auth-1"}

        monkeypatch.setattr(retry_worker, "call_payment_gateway", flaky)
        monkeypatch.setattr(retry_worker.time, "sleep", lambda _: None)

        assert process_payment_event(event) == "SUCCESS"
        assert event.retry_count == 2

    def test_gateway_timeout_current_behaviour_is_permanent_failure(
        self, event, monkeypatch
    ):
        """Documents today's (buggy) behaviour: fails immediately, no retries."""
        calls = {"count": 0}

        def always_timeout(_):
            calls["count"] += 1
            raise GatewayTimeoutError("timeout")

        monkeypatch.setattr(retry_worker, "call_payment_gateway", always_timeout)

        assert process_payment_event(event) == "FAILED"
        assert event.status == "FAILED"
        assert event.retry_count == 0
        assert calls["count"] == 1


class TestLogRetryStatus:
    def test_logs_audit_line(self, event, caplog):
        event.retry_count = 2

        with caplog.at_level(logging.INFO, logger=retry_worker.__name__):
            assert log_retry_status(event, 3, "timeout") is None

        assert "[AUDIT]" in caplog.text
        assert "event=EVT-001" in caplog.text
        assert "attempt=3" in caplog.text
        assert "retry_count=2" in caplog.text
        assert "error=timeout" in caplog.text
