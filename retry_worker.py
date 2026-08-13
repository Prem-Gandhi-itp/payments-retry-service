"""
Payment Retry Worker — payments-retry-service
Processes payment events and handles retries.

Transient gateway failures (GatewayTimeoutError) are retried with exponential
backoff. Unexpected errors are logged with a traceback and propagated to the
caller instead of being swallowed.
"""

import logging
import time

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds


class GatewayTimeoutError(Exception):
    """Raised when the payment gateway does not respond in time."""
    pass


class PaymentRetriesExhaustedError(Exception):
    """Raised when a payment event still fails after all retries."""

    def __init__(self, event: "PaymentEvent", last_error: Exception):
        super().__init__(
            f"Payment {event.event_id} failed after {event.retry_count} retries: "
            f"{last_error}"
        )
        self.event = event
        self.last_error = last_error


class PaymentEvent:
    def __init__(self, event_id: str, amount: float, currency: str):
        self.event_id = event_id
        self.amount = amount
        self.currency = currency
        self.status = "PENDING"
        self.retry_count = 0


def call_payment_gateway(event: PaymentEvent) -> dict:
    """
    Simulate a call to the external payment gateway.
    Raises GatewayTimeoutError on transient failures.
    """
    # Simulated: always times out for demonstration
    raise GatewayTimeoutError(f"Gateway timeout for event {event.event_id}")


def process_payment_event(event: PaymentEvent) -> str:
    """
    Attempt the payment, retrying transient gateway timeouts with exponential
    backoff.

    Returns "SUCCESS" once the gateway accepts the payment.
    Raises PaymentRetriesExhaustedError when every attempt timed out, and
    re-raises any other exception after marking the event FAILED.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = call_payment_gateway(event)
        except GatewayTimeoutError as e:
            event.retry_count = attempt
            event.status = "RETRYING"
            log_retry_status(event, attempt, str(e))
            if attempt == MAX_RETRIES:
                event.status = "FAILED"
                logger.error(
                    "Payment %s exhausted %d retries", event.event_id, MAX_RETRIES,
                    exc_info=True,
                )
                raise PaymentRetriesExhaustedError(event, e) from e
            time.sleep(BACKOFF_BASE ** attempt)
        except Exception:
            event.status = "FAILED"
            logger.exception(
                "Payment %s failed with an unexpected error", event.event_id
            )
            raise
        else:
            event.status = "SUCCESS"
            logger.info("Payment %s succeeded: %s", event.event_id, result)
            return "SUCCESS"

    # Unreachable: the loop either returns or raises.
    raise AssertionError("retry loop exited without a result")


def log_retry_status(event: PaymentEvent, attempt: int, error: str) -> None:
    """Log retry attempt to audit table (stub)."""
    # TODO: write to audit_table in database
    logger.info(
        "[AUDIT] event=%s attempt=%s retry_count=%s error=%s",
        event.event_id, attempt, event.retry_count, error,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    event = PaymentEvent("EVT-001", 99.99, "USD")
    try:
        result = process_payment_event(event)
    except PaymentRetriesExhaustedError as e:
        logger.error("Giving up on event %s: %s", event.event_id, e)
        result = event.status
    print(f"Final status: {result}, retry_count: {event.retry_count}")
