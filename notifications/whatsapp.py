"""
Notifications — sends messages to Ashray via WhatsApp through OpenClaw.

OpenClaw manages the WhatsApp connection. We shell out to the
`openclaw message send` CLI — no WhatsApp protocol handling needed.

The target is Ashray's own number (self-chat), since selfChatMode is enabled
in the OpenClaw WhatsApp config.

Usage (from other modules):
  from notifications.whatsapp import send, send_health_alert
  send("Your Whoop recovery is 34 — take it easy today.")
"""
import subprocess
import sys

# Ashray's WhatsApp number (E.164 format)
# selfChatMode=true means OpenClaw will deliver this to your own chat
ASHRAY_WHATSAPP = "+16099379394"


def send(message: str, dry_run: bool = False) -> bool:
    """
    Send a WhatsApp message via OpenClaw CLI.
    Returns True on success, False on failure.
    """
    cmd = [
        "openclaw", "message", "send",
        "--channel", "whatsapp",
        "--target", ASHRAY_WHATSAPP,
        "--message", message,
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print(f"[notifications] send failed (exit {result.returncode}): {result.stderr.strip()}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[notifications] send error: {e}", file=sys.stderr)
        return False


def send_health_alert(title: str, body: str) -> bool:
    """Formatted health alert."""
    return send(f"⚡ *{title}*\n\n{body}")


def send_daily_summary(recovery: int, readiness: int, hrv: float, notes: str = "") -> bool:
    """Daily morning health summary."""
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


if __name__ == "__main__":
    # Quick test
    send("⚡ Life OS notifications are wired up.", dry_run="--dry-run" in sys.argv)
