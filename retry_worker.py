"""
Payment Retry Worker — payments-retry-service
Processes payment events and handles retries.

BUG: GatewayTimeoutError is not retried — it falls through to the generic
     except block and marks the event as permanently FAILED.
"""

import logging
import time

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds


class GatewayTimeoutError(Exception):
    """Raised when the payment gateway does not respond in time."""
    pass


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
    BUG IS HERE:
    GatewayTimeoutError is caught by the generic `except Exception` block.
    The event is immediately marked FAILED with no retry attempted.
    retry_count stays at 0.
    """
    try:
        result = call_payment_gateway(event)
        event.status = "SUCCESS"
        logger.info(f"Payment {event.event_id} succeeded: {result}")
        return "SUCCESS"

    except Exception as e:
        # BUG: This catches GatewayTimeoutError too — should retry instead
        event.status = "FAILED"
        logger.error(f"Payment {event.event_id} failed permanently: {e}")
        return "FAILED"


def log_retry_status(event: PaymentEvent, attempt: int, error: str) -> None:
    """Log retry attempt to audit table (stub)."""
    # TODO: write to audit_table in database
    logger.info(
        f"[AUDIT] event={event.event_id} attempt={attempt} "
        f"retry_count={event.retry_count} error={error}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    event = PaymentEvent("EVT-001", 99.99, "USD")
    result = process_payment_event(event)
    print(f"Final status: {result}, retry_count: {event.retry_count}")
