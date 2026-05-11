#!/usr/bin/env python3
"""Simple load test for outbound rate-limited queue behavior.

This does NOT hit Telegram. It simulates 500+ chats sending messages
through the same rate limiter used by the bot, and reports timings.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass

GLOBAL_MIN_INTERVAL = 1.0 / 30.0  # ~30 msg/sec total
PER_CHAT_INTERVAL = 1.0           # ~1 msg/sec per chat

GLOBAL_LAST_SENT = 0.0
CHAT_LAST_SENT: dict[int, float] = {}


@dataclass
class QueueItem:
    chat_id: int
    enqueued_at: float
    future: asyncio.Future


async def _rate_limit_send(chat_id: int | None) -> None:
    global GLOBAL_LAST_SENT

    now = time.monotonic()
    wait_s = max(0.0, GLOBAL_MIN_INTERVAL - (now - GLOBAL_LAST_SENT))
    if chat_id is not None:
        last_chat = CHAT_LAST_SENT.get(chat_id, 0.0)
        wait_s = max(wait_s, PER_CHAT_INTERVAL - (now - last_chat))

    if wait_s > 0:
        await asyncio.sleep(wait_s)

    now = time.monotonic()
    GLOBAL_LAST_SENT = now
    if chat_id is not None:
        CHAT_LAST_SENT[chat_id] = now


async def _worker(queue: asyncio.Queue, stats: dict) -> None:
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break

        await _rate_limit_send(item.chat_id)
        sent_at = time.monotonic()
        latency = sent_at - item.enqueued_at
        stats["count"] += 1
        stats["latency_sum"] += latency
        stats["latency_max"] = max(stats["latency_max"], latency)
        if not item.future.done():
            item.future.set_result(sent_at)
        queue.task_done()


async def run_test(users: int, messages_per_user: int, workers: int) -> None:
    queue: asyncio.Queue = asyncio.Queue()
    stats = {"count": 0, "latency_sum": 0.0, "latency_max": 0.0}

    worker_tasks = [asyncio.create_task(_worker(queue, stats)) for _ in range(workers)]

    start = time.monotonic()
    futures: list[asyncio.Future] = []

    for user_id in range(1, users + 1):
        for _ in range(messages_per_user):
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            futures.append(fut)
            await queue.put(QueueItem(chat_id=user_id, enqueued_at=time.monotonic(), future=fut))

    await queue.join()

    for _ in worker_tasks:
        await queue.put(None)
    await asyncio.gather(*worker_tasks)

    end = time.monotonic()
    total = stats["count"]
    avg_latency = stats["latency_sum"] / total if total else 0.0

    print("Load test results")
    print("-----------------")
    print(f"Users: {users}")
    print(f"Messages per user: {messages_per_user}")
    print(f"Workers: {workers}")
    print(f"Total messages: {total}")
    print(f"Total time: {end - start:.2f}s")
    print(f"Avg enqueue->send latency: {avg_latency:.2f}s")
    print(f"Max enqueue->send latency: {stats['latency_max']:.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate outbound queue throughput")
    parser.add_argument("--users", type=int, default=500)
    parser.add_argument("--messages", type=int, default=1, dest="messages_per_user")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    asyncio.run(run_test(args.users, args.messages_per_user, args.workers))


if __name__ == "__main__":
    main()
