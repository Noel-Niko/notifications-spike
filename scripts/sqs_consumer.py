"""SQS consumer for EventBridge transcription events.

Polls the Genesys transcription SQS queue and saves events as JSONL
per conversation to EventBridge/conversation_events/<conversation-id>.jsonl.

Usage:
    export SQS_QUEUE_URL="https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test"
    export AWS_PROFILE="765425735388_admin-role"
    uv run python -m scripts.sqs_consumer
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure functions (testable without boto3)
# ---------------------------------------------------------------------------


def parse_sqs_message(
    body: str,
    received_at: float,
    sqs_sent_timestamp: int | None,
) -> dict:
    """Parse an SQS message body (EventBridge envelope) into our JSONL format.

    Args:
        body: The SQS message body — a JSON string of the EventBridge event.
        received_at: Local wall-clock time (time.time()) when we received the message.
        sqs_sent_timestamp: SQS SentTimestamp attribute (epoch ms), or None.

    Returns:
        Dict ready to be serialized as one JSONL line, or ``None`` if the
        event has no transcripts (e.g. status-only events like SESSION_ONGOING).
    """
    raw_event = json.loads(body)
    event_body = raw_event["detail"]["eventBody"]

    transcripts = event_body.get("transcripts")
    if not transcripts:
        return None

    return {
        "conversationId": event_body["conversationId"],
        "receivedAt": received_at,
        "sqsSentTimestamp": sqs_sent_timestamp,
        "ebTime": raw_event["time"],
        "genesysEventTime": event_body["eventTime"],
        "sessionStartTimeMs": event_body["sessionStartTimeMs"],
        "transcripts": transcripts,
        "rawEvent": raw_event,
    }


def save_event(parsed: dict, output_dir: Path) -> Path:
    """Append a parsed event as one JSON line to the conversation's JSONL file.

    Creates output_dir and the file if they don't exist.

    Returns:
        Path to the JSONL file written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{parsed['conversationId']}.jsonl"
    with file_path.open("a") as f:
        f.write(json.dumps(parsed) + "\n")
    return file_path


# ---------------------------------------------------------------------------
# SQS polling (AWS interaction)
# ---------------------------------------------------------------------------


def poll_sqs(
    queue_url: str, profile: str, output_dir: Path, region: str | None = None
) -> None:
    """Poll SQS queue for EventBridge transcription events.

    Long-polls the queue, parses each message, saves to JSONL, and deletes
    the message. Runs until SIGINT/SIGTERM.

    Args:
        queue_url: Full SQS queue URL.
        profile: AWS profile name for boto3 session.
        output_dir: Directory to save conversation JSONL files.
        region: AWS region name (e.g. ``us-east-2``).
    """
    import boto3  # Lazy import — only needed for actual polling

    session = boto3.Session(profile_name=profile, region_name=region)
    sqs = session.client("sqs")

    running = True

    def _shutdown(signum: int, frame: object) -> None:
        nonlocal running
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, shutting down gracefully...", sig_name)
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Polling SQS queue: %s", queue_url)
    logger.info("Saving events to: %s", output_dir)

    while running:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,
                AttributeNames=["SentTimestamp"],
            )
        except Exception:
            logger.exception("Error receiving messages from SQS")
            if running:
                time.sleep(5)
            continue

        messages = response.get("Messages", [])
        if not messages:
            continue

        for msg in messages:
            received_at = time.time()
            sqs_sent_raw = msg.get("Attributes", {}).get("SentTimestamp")
            sqs_sent_timestamp = int(sqs_sent_raw) if sqs_sent_raw else None

            try:
                parsed = parse_sqs_message(msg["Body"], received_at, sqs_sent_timestamp)
                if parsed is not None:
                    file_path = save_event(parsed, output_dir)
                    logger.info(
                        "Saved event for conversation %s to %s",
                        parsed["conversationId"],
                        file_path,
                    )
                else:
                    logger.debug("Skipping non-transcript event: %s", msg.get("MessageId"))
            except Exception:
                logger.exception("Error processing message: %s", msg.get("MessageId"))

            try:
                sqs.delete_message(
                    QueueUrl=queue_url,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
            except Exception:
                logger.exception(
                    "Error deleting message %s", msg.get("MessageId")
                )

    logger.info("SQS consumer stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    queue_url = os.environ.get("SQS_QUEUE_URL")
    if not queue_url:
        logger.error("SQS_QUEUE_URL environment variable is required")
        sys.exit(1)

    profile = os.environ.get("AWS_PROFILE", "765425735388_admin-role")
    region = os.environ.get("AWS_REGION", "us-east-2")
    output_dir = Path(os.environ.get("EB_EVENT_DIR", "EventBridge/conversation_events"))

    poll_sqs(queue_url=queue_url, profile=profile, output_dir=output_dir, region=region)


if __name__ == "__main__":
    main()
