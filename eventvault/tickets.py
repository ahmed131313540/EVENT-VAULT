"""Ticket tokens, QR codes and the PDF ticket."""
import re
import secrets
from io import BytesIO

import segno
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

# 30 characters with no 0/O/1/I/L/U so codes are easy to read out or type at the door
ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"


def new_token() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(16))
    return "EV-" + "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def normalize_token(text: str):
    """Accepts a scanned or typed code in any case, with or without dashes/spaces. Returns EV-XXXX-XXXX-XXXX-XXXX or None."""
    chars = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    if len(chars) != 18 or not chars.startswith("EV") or any(c not in ALPHABET for c in chars[2:]):
        return None
    body = chars[2:]
    return "EV-" + "-".join(body[i:i + 4] for i in range(0, 16, 4))


def qr_rows(data: str):
    return [[bool(v) for v in row] for row in segno.make(data, error="q", micro=False).matrix]


def qr_svg(data: str, dark="#0B1020", light="#FFFFFF", quiet=3) -> str:
    rows = qr_rows(data)
    n = len(rows)
    size = n + quiet * 2
    cells = "".join(f"M{x + quiet} {y + quiet}h1v1h-1z" for y, row in enumerate(rows) for x, on in enumerate(row) if on)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
            f'<rect width="{size}" height="{size}" fill="{light}"/><path d="{cells}" fill="{dark}"/></svg>')


def _safe(s) -> str:
    """The built-in PDF fonts only cover Latin-1; swap anything else for '?' instead of drawing boxes."""
    return str(s or "").encode("cp1252", "replace").decode("cp1252")


def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _fit(c, text, font, max_size, min_size, width, max_lines):
    size = max_size
    while size >= min_size:
        lines = simpleSplit(text, font, size, width)
        if len(lines) <= max_lines:
            return size, lines
        size -= 1
    lines = simpleSplit(text, font, min_size, width)[:max_lines]
    lines[-1] = lines[-1][:-1] + "…" if lines else ""
    return min_size, lines


def build_ticket_pdf(t: dict) -> bytes:
    """t keys: token, event_title, starts_at (datetime), venue, city, tier_name, holder_name, seq, total, order_ref."""
    W, H = 720, 300
    NAVY, CARD, PURPLE, PINK, GOLD = HexColor("#0B1020"), HexColor("#182238"), HexColor("#7C3AED"), HexColor("#EC4899"), HexColor("#F59E0B")
    TEXT, MUTED, BORDER = HexColor("#F8FAFC"), HexColor("#94A3B8"), HexColor("#263452")

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(_safe(f"{t['event_title']} - ticket {t['token']}"))
    c.setAuthor("Event Vault")

    # background + soft glows
    c.setFillColor(NAVY)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(PURPLE); c.setFillAlpha(0.20); c.circle(90, H + 30, 190, fill=1, stroke=0)
    c.setFillColor(PINK); c.setFillAlpha(0.13); c.circle(430, -30, 170, fill=1, stroke=0)
    c.setFillAlpha(1)

    # gradient bar (purple -> pink) along the top
    steps = 120
    p, k = (0x7C / 255, 0x3A / 255, 0xED / 255), (0xEC / 255, 0x48 / 255, 0x99 / 255)
    for i in range(steps):
        r, g, b = _lerp(p, k, i / (steps - 1))
        c.setFillColor(Color(r, g, b))
        c.rect(i * W / steps, H - 9, W / steps + 1, 9, fill=1, stroke=0)

    # brand
    c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 13)
    c.drawString(38, H - 42, "EVENT VAULT")
    c.setFillColor(PINK); c.circle(30, H - 38, 3.2, fill=1, stroke=0)

    # tier badge
    tier = _safe(t["tier_name"]).upper()
    c.setFont("Helvetica-Bold", 10)
    bw = c.stringWidth(tier, "Helvetica-Bold", 10) + 24
    c.setStrokeColor(GOLD); c.setLineWidth(1); c.roundRect(38, H - 84, bw, 22, 11, fill=0, stroke=1)
    c.setFillColor(GOLD); c.drawString(50, H - 77, tier)

    # title
    size, lines = _fit(c, _safe(t["event_title"]), "Helvetica-Bold", 27, 16, 400, 2)
    c.setFillColor(TEXT); c.setFont("Helvetica-Bold", size)
    y = H - 118
    for line in lines:
        c.drawString(38, y, line)
        y -= size + 3

    # when / where
    dt = t["starts_at"]
    when = dt.strftime("%a %d %b %Y") + "   " + dt.strftime("%I:%M %p").lstrip("0")
    c.setFillColor(GOLD); c.setFont("Helvetica-Bold", 13)
    c.drawString(38, 96, _safe(when))
    c.setFillColor(MUTED); c.setFont("Helvetica", 11)
    c.drawString(38, 78, _safe(f"{t['venue']}, {t['city']}")[:70])

    # holder
    c.setStrokeColor(BORDER); c.setLineWidth(0.8); c.line(38, 60, 450, 60)
    c.setFillColor(MUTED); c.setFont("Helvetica", 8.5)
    c.drawString(38, 44, "TICKET HOLDER"); c.drawString(300, 44, "TICKET")
    c.setFillColor(TEXT); c.setFont("Helvetica-Bold", 12)
    c.drawString(38, 28, _safe(t["holder_name"])[:34])
    c.drawString(300, 28, f"{t['seq']} of {t['total']}")
    c.setFillColor(MUTED); c.setFont("Helvetica", 8.5)
    c.drawRightString(450, 28, f"Order {t['order_ref'][:10].upper()}")

    # perforation
    c.setStrokeColor(BORDER); c.setDash(3, 4); c.setLineWidth(1.2); c.line(482, 20, 482, H - 22); c.setDash()
    c.setFillColor(NAVY)
    c.circle(482, H, 9, fill=1, stroke=0); c.circle(482, 0, 9, fill=1, stroke=0)

    # QR card (white so scanners read it reliably)
    cx, cy, cs = 506, 66, 178
    c.setFillColor(HexColor("#FFFFFF")); c.roundRect(cx, cy, cs, cs, 14, fill=1, stroke=0)
    rows = qr_rows(t["token"])
    n = len(rows)
    mod = (cs - 28) / n
    ox, oy = cx + 14, cy + 14
    c.setFillColor(NAVY)
    for r, row in enumerate(rows):
        for col, on in enumerate(row):
            if on:
                c.rect(ox + col * mod, oy + (n - 1 - r) * mod, mod + 0.35, mod + 0.35, fill=1, stroke=0)

    c.setFillColor(TEXT); c.setFont("Courier-Bold", 10)
    c.drawCentredString(cx + cs / 2, 46, t["token"])
    c.setFillColor(MUTED); c.setFont("Helvetica", 8.5)
    c.drawCentredString(cx + cs / 2, 30, "Scan at the entrance. Valid for one entry.")

    c.showPage()
    c.save()
    return buf.getvalue()
