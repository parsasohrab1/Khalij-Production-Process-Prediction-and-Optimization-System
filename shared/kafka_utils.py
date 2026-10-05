"""Helper functions for producing and consuming messages from Kafka (sensor data streaming, R-GEN-01).

Phase 7: high-throughput configuration (compression, linger, idempotence, batch) for the 50k-sensor scale.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterator
from datetime import datetime

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer

logger = logging.getLogger(__name__)


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def high_throughput_producer_config(bootstrap_servers: str, client_id: str = "khalij-pos") -> dict:
    """Producer configuration optimized for high throughput (phase 7)."""
    return {
        "bootstrap.servers": bootstrap_servers,
        "client.id": client_id,
        "acks": os.getenv("KAFKA_ACKS", "1"),
        "retries": int(os.getenv("KAFKA_RETRIES", "5")),
        "retry.backoff.ms": 200,
        "linger.ms": int(os.getenv("KAFKA_LINGER_MS", "20")),
        "batch.size": int(os.getenv("KAFKA_BATCH_SIZE", "65536")),
        "compression.type": os.getenv("KAFKA_COMPRESSION", "lz4"),
        "queue.buffering.max.messages": int(os.getenv("KAFKA_QUEUE_MAX_MESSAGES", "100000")),
        "queue.buffering.max.kbytes": int(os.getenv("KAFKA_QUEUE_MAX_KBYTES", "1048576")),
        "enable.idempotence": os.getenv("KAFKA_IDEMPOTENCE", "false").lower() == "true",
    }


def high_throughput_consumer_config(bootstrap_servers: str, group_id: str) -> dict:
    return {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
        "fetch.min.bytes": int(os.getenv("KAFKA_FETCH_MIN_BYTES", "1024")),
        "fetch.wait.max.ms": int(os.getenv("KAFKA_FETCH_WAIT_MS", "50")),
        "max.partition.fetch.bytes": int(os.getenv("KAFKA_MAX_PARTITION_FETCH", "1048576")),
    }


class KafkaEventProducer:
    """Lightweight wrapper over confluent_kafka.Producer for sending JSON messages."""

    def __init__(self, bootstrap_servers: str, client_id: str = "khalij-pos", high_throughput: bool = True):
        cfg = (
            high_throughput_producer_config(bootstrap_servers, client_id)
            if high_throughput
            else {
                "bootstrap.servers": bootstrap_servers,
                "client.id": client_id,
                "retries": 5,
                "retry.backoff.ms": 500,
            }
        )
        self._producer = Producer(cfg)
        self._queued = 0
        self._sent = 0
        self._errors = 0

    def send(self, topic: str, payload: dict, key: str | None = None) -> None:
        try:
            self._producer.produce(
                topic=topic,
                key=key.encode("utf-8") if isinstance(key, str) else key,
                value=json.dumps(payload, default=_json_default).encode("utf-8"),
                callback=self._delivery_callback,
            )
            self._queued += 1
            self._producer.poll(0)
        except BufferError:
            logger.warning("Kafka producer queue is full, waiting for flush...")
            self._producer.flush(5)
            self._producer.produce(
                topic=topic,
                key=key.encode("utf-8") if isinstance(key, str) else key,
                value=json.dumps(payload, default=_json_default).encode("utf-8"),
                callback=self._delivery_callback,
            )
            self._queued += 1

    def send_batch(self, topic: str, payloads: list[dict], key_fn: Callable[[dict], str | None] | None = None) -> int:
        """Batch send with a single poll at the end."""
        sent = 0
        for payload in payloads:
            key = key_fn(payload) if key_fn else None
            try:
                self._producer.produce(
                    topic=topic,
                    key=key.encode("utf-8") if isinstance(key, str) else key,
                    value=json.dumps(payload, default=_json_default).encode("utf-8"),
                    callback=self._delivery_callback,
                )
                sent += 1
                self._queued += 1
            except BufferError:
                self._producer.poll(0.1)
                try:
                    self._producer.produce(
                        topic=topic,
                        key=key.encode("utf-8") if isinstance(key, str) else key,
                        value=json.dumps(payload, default=_json_default).encode("utf-8"),
                        callback=self._delivery_callback,
                    )
                    sent += 1
                    self._queued += 1
                except BufferError:
                    logger.error("Batch produce stopped; the queue is full.")
                    break
        self._producer.poll(0)
        return sent

    def _delivery_callback(self, err, msg):
        if err is not None:
            self._errors += 1
            logger.error("Failed to send a message to Kafka: %s", err)
        else:
            self._sent += 1

    def flush(self, timeout: float = 10.0) -> None:
        self._producer.flush(timeout)

    def stats(self) -> dict:
        return {"queued": self._queued, "delivered": self._sent, "errors": self._errors}


class KafkaEventConsumer:
    """Lightweight wrapper over confluent_kafka.Consumer for consuming JSON messages."""

    def __init__(self, bootstrap_servers: str, group_id: str, topics: list[str], high_throughput: bool = True):
        cfg = (
            high_throughput_consumer_config(bootstrap_servers, group_id)
            if high_throughput
            else {
                "bootstrap.servers": bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": "latest",
                "enable.auto.commit": True,
            }
        )
        self._consumer = Consumer(cfg)
        self._consumer.subscribe(topics)

    def poll_messages(self, timeout: float = 1.0) -> Iterator[dict]:
        while True:
            msg = self._consumer.poll(timeout)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(msg.error())
            try:
                yield json.loads(msg.value().decode("utf-8"))
            except json.JSONDecodeError:
                logger.warning("An invalid JSON message was received and ignored.")

    def run(self, handler: Callable[[dict], None]) -> None:
        for message in self.poll_messages():
            handler(message)

    def close(self) -> None:
        self._consumer.close()
