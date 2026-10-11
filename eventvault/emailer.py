"""Sends email through Resend's HTTP API (no SDK needed)."""
import base64
import json
import urllib.error
import urllib.request

from . import config


def email_enabled() -> bool:
    return bool(config.RESEND_API_KEY)


def send_email(to, subject, html, text, attachments=None, reply_to=None, idempotency_key=None):
    """Returns (ok, error_message)."""
    if not email_enabled():
        return False, "Email isn't configured (RESEND_API_KEY is not set)."
    payload = {"from": config.EMAIL_FROM, "to": [to], "subject": subject, "html": html, "text": text}
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        payload["attachments"] = [{"filename": n, "content": base64.b64encode(b).decode()} for n, b in attachments]
    headers = {"Authorization": f"Bearer {config.RESEND_API_KEY}", "Content-Type": "application/json",
               "User-Agent": "eventvault/1.0"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300, None
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("message", "")
        except Exception:
            detail = ""
        return False, f"Resend rejected the email ({e.code}). {detail}".strip()
    except Exception as e:
        return False, f"Couldn't reach Resend: {e}"


def ticket_email_html(buyer_name, event, tickets, order_ref, site_url):
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    when = event["starts_at"].strftime("%A %d %B %Y, ") + event["starts_at"].strftime("%I:%M %p").lstrip("0")
    rows = "".join(
        f'<tr><td style="padding:10px 0;border-top:1px solid #263452;color:#F8FAFC;font-size:14px">{esc(t["tier_name"])}</td>'
        f'<td style="padding:10px 0;border-top:1px solid #263452;color:#94A3B8;font-size:13px;text-align:right;font-family:Courier New,monospace">{esc(t["token"])}</td></tr>'
        for t in tickets)
    link = f'<p style="margin:22px 0 0"><a href="{esc(site_url)}/#/dashboard/tickets" style="color:#EC4899">View your tickets online</a></p>' if site_url else ""
    return f"""<!doctype html><html><body style="margin:0;background:#0B1020;padding:24px 12px;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#182238;border:1px solid #263452;border-radius:16px;overflow:hidden">
<tr><td style="height:6px;background:#7C3AED;background-image:linear-gradient(90deg,#7C3AED,#EC4899)"></td></tr>
<tr><td style="padding:30px 30px 8px">
<div style="color:#F8FAFC;font-weight:700;font-size:15px;letter-spacing:.5px">EVENT VAULT</div>
<h1 style="color:#F8FAFC;font-size:24px;margin:18px 0 6px">You're going, {esc(buyer_name.split(" ")[0])}.</h1>
<p style="color:#94A3B8;font-size:15px;line-height:1.5;margin:0 0 20px">Your {len(tickets)} ticket{'s' if len(tickets) != 1 else ''} for <b style="color:#F8FAFC">{esc(event['title'])}</b> {'are' if len(tickets) != 1 else 'is'} attached as PDF. Show the QR code on your phone or print it. Each code works once.</p>
<p style="color:#F59E0B;font-size:15px;font-weight:700;margin:0 0 2px">{esc(when)}</p>
<p style="color:#94A3B8;font-size:14px;margin:0 0 22px">{esc(event['venue'])}, {esc(event['city'])}</p>
<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>
{link}
<p style="color:#94A3B8;font-size:12px;margin:26px 0 0;padding-bottom:26px">Order {esc(order_ref)}. Questions about the event? Reply to this email to reach the organiser.</p>
</td></tr></table></td></tr></table></body></html>"""


def ticket_email_text(buyer_name, event, tickets, order_ref):
    lines = "\n".join(f"- {t['tier_name']}: {t['token']}" for t in tickets)
    return (f"You're going, {buyer_name.split(' ')[0]}.\n\nYour tickets for {event['title']} are attached as PDF.\n"
            f"{event['starts_at'].strftime('%A %d %B %Y, %I:%M %p')} - {event['venue']}, {event['city']}\n\n{lines}\n\nOrder {order_ref}")
