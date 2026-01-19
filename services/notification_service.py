"""Generic notification service.

This is intentionally minimal: it provides a `send_notification` function
that currently logs the message. Replace or extend this with concrete
channels (email, pagerduty, webhook) as needed in the future.
"""
import logging

logger = logging.getLogger(__name__)


def send_notification(message: str, channel: str | None = None) -> bool:
    """Send a notification (currently logs message).

    Returns True if delivery is considered successful.
    """
    try:
        if channel:
            logger.info("Notification to %s: %s", channel, message)
        else:
            logger.info("Notification: %s", message)
        return True
    except Exception as e:
        # Keep this service resilient - do not raise.
        logger.exception("Failed to send notification: %s", e)
        return False
