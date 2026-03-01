"""
Notifications — queues messages for Zoe (the OpenClaw agent) to deliver via WhatsApp.

Architecture:
  The Python scheduler cannot call WhatsApp directly (OpenClaw's message tool
  is blocked over HTTP for security). Instead, we write notifications to a
  queue file. Zoe checks this file on heartbeat and delivers them.

  Queue file: /Users/redtriangle/.openclaw/workspace/life-os/notifications/queue.json

Queue format:
  [{"id": "...", "message": "...", "created_at": "...", "delivered": false}, ...]
"""
import json
import os
import uuid
from datetime import datetime, timezone

WHATSAPP_TARGET = "+16099379394"
TELEGRAM_CHAT_ID = "184558135"

QUEUE_FILE = os.path.join(os.path.dirname(__file__), "queue.json")


def _load_queue() -> list:
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE) as f:
        return json.load(f)


def _save_queue(queue: list):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def send(message: str) -> str:
    """
    Queue a WhatsApp message for delivery by Zoe on next heartbeat.
    Returns the message id.
    """
    queue = _load_queue()
    entry = {
        "id": str(uuid.uuid4()),
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "delivered": False,
    }
    queue.append(entry)
    _save_queue(queue)
    print(f"[notifications] queued message {entry['id']}")
    return entry["id"]


def send_health_alert(title: str, body: str) -> str:
    return send(f"⚡ *{title}*\n\n{body}")


def send_daily_summary(recovery: int, readiness: int, hrv: float, notes: str = "") -> str:
    emoji = "🟢" if recovery >= 67 else "🟡" if recovery >= 34 else "🔴"
    msg = (
        f"{emoji} *Morning Summary*\n\n"
        f"Whoop Recovery: {recovery}\n"
        f"Oura Readiness: {readiness}\n"
        f"HRV: {hrv:.1f}ms\n"
    )
    if notes:
        msg += f"\n{notes}"
    return send(msg)


def get_pending() -> list:
    """Return all undelivered messages."""
    return [m for m in _load_queue() if not m["delivered"]]


def mark_delivered(message_id: str):
    """Mark a message as delivered."""
    queue = _load_queue()
    for m in queue:
        if m["id"] == message_id:
            m["delivered"] = True
    _save_queue(queue)


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        pending = get_pending()
        if not pending:
            print("NO_PENDING")
        else:
            for m in pending:
                print(f"PENDING:{m['id']}:{m['message']}")
    elif "--queue" in sys.argv:
        # Quick test: queue a message from CLI
        msg = " ".join(sys.argv[2:]) or "test"
        send(msg)
        print(f"Queued: {msg}")
