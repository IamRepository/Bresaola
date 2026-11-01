"""PDF summary of one batch: result, timeline, recipe, cure, drying, notes and photos.

build_pdf(con, pid) -> bytes. Works for finished and unfinished batches; an unfinished one
is marked "summary so far". Uses the bundled DejaVu fonts so notes with any accents or
symbols print correctly on every machine.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (HRFlowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from . import __version__, calc, db, safety, sensors, storage

FONT_DIR = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")

RED = colors.HexColor("#7a2320")
INK = colors.HexColor("#2e2a28")
MUTED = colors.HexColor("#7d7672")
LINE = colors.HexColor("#e3dedb")
SOFT = colors.HexColor("#f8f5f3")
HEAD_BG = colors.HexColor("#efe5e2")
GREEN = colors.HexColor("#3d5a45")

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
BODY_W = PAGE_W - 2 * MARGIN

S = {
    "title": ParagraphStyle("title", fontName="DejaVu-Bold", fontSize=19, leading=23, textColor=INK),
    "sub": ParagraphStyle("sub", fontName="DejaVu", fontSize=9, leading=12, textColor=MUTED),
    "h2": ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=12.5, leading=16, textColor=RED,
                         spaceBefore=12, spaceAfter=1, keepWithNext=1),    # never alone at a page end
    "kicker": ParagraphStyle("kicker", fontName="DejaVu-Bold", fontSize=7.5, leading=10, textColor=RED),
    "head": ParagraphStyle("head", fontName="DejaVu-Bold", fontSize=8, leading=10, textColor=INK),
    "body": ParagraphStyle("body", fontName="DejaVu", fontSize=9, leading=12.5, textColor=INK),
    "small": ParagraphStyle("small", fontName="DejaVu", fontSize=7.5, leading=10, textColor=MUTED),
    "lab": ParagraphStyle("lab", fontName="DejaVu", fontSize=7.5, leading=9.5, textColor=MUTED),
    "val": ParagraphStyle("val", fontName="DejaVu-Bold", fontSize=13, leading=16, textColor=INK),
    "h3": ParagraphStyle("h3", fontName="DejaVu-Bold", fontSize=9.5, leading=12, textColor=INK, keepWithNext=1,
                         spaceBefore=6, spaceAfter=2),
    "cell": ParagraphStyle("cell", fontName="DejaVu", fontSize=8, leading=10, textColor=INK, alignment=TA_LEFT),
}


def _h2(num: int, title: str) -> list:
    """Numbered section heading with a rule under it (kept with what follows)."""
    rule = HRFlowable(width="100%", thickness=0.8, color=RED, spaceBefore=1, spaceAfter=6)
    rule.keepWithNext = 1
    return [Paragraph(f"{num}&nbsp;&nbsp;{_text(title)}", S["h2"]), rule]


def _notes(label: str, text: str | None) -> list:
    """A step's own notes, inside that step's section (owner, 1 Nov 2026)."""
    if not text or not text.strip():
        return []
    out = [Paragraph(_text(label), S["h3"])]
    out += [Paragraph(_text(part), S["body"]) for part in text.split("\n\n")]
    return out + [Spacer(1, 4)]


def _d(s):
    return date.fromisoformat(s[:10]) if s else None


def _fd(s_or_d) -> str:
    if not s_or_d:
        return "–"
    v = s_or_d if isinstance(s_or_d, date) else _d(s_or_d)
    return f"{v.day} {v:%b %Y}"


def _text(s: str | None) -> str:
    """User text → safe Paragraph markup (escape, keep line breaks)."""
    return escape(s or "").replace("\n", "<br/>")


CELL_MAX = 300          # characters of user text in a table cell; the rest goes under Notes
CELL_LINES = 6          # line breaks in a table cell


def _cell_text(s: str | None, label: str, overflow: list) -> str:
    """Table cells can't split across pages: a note longer than a page made reportlab give up
    (LayoutError) and the download did nothing (audit 26 Oct, #3). Shorten long cell text and keep
    the full text, printed at the end of the same section."""
    s = s or ""
    if len(s) <= CELL_MAX and s.count("\n") < CELL_LINES:
        return s
    overflow.append((label, s))
    short = " ".join(s[:CELL_MAX].split())                  # line breaks folded into spaces
    short = short.rsplit(" ", 1)[0] if " " in short else short
    return short + " … (full text below)"


def _table(rows, widths, header=True, align_right=()):
    data = [[c if isinstance(c, Paragraph) else Paragraph(_text(str(c)), S["cell"]) for c in r] for r in rows]
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        data[0] = [Paragraph(c.text, ParagraphStyle("hd", parent=S["head"], alignment=c.style.alignment))
                   if isinstance(c, Paragraph) else c for c in data[0]]
        style += [("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("LINEBELOW", (0, 0), (-1, 0), 0.8, RED),
                  ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SOFT])]
    for col in align_right:
        style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle(style))
    return t


def _right(rows, cols):
    """Wrap numeric cells so they align right inside Paragraph tables."""
    st = ParagraphStyle("r", parent=S["cell"], alignment=2)
    return [[Paragraph(_text(str(c)), st) if i in cols else c for i, c in enumerate(r)] for r in rows]


WARN = colors.HexColor("#8a5a00")
WARN_BG = colors.HexColor("#fbf1dc")


NOTE = colors.HexColor("#2f5d7c")
NOTE_BG = colors.HexColor("#eaf2f7")


def _alert(text: str, level: str = "warning"):
    """One box style for safety messages: the level in a narrow left column, the text beside it."""
    fg, bg, label = (WARN, WARN_BG, "Warning") if level == "warning" else (NOTE, NOTE_BG, "Note")
    t = Table([[Paragraph(f"<b>{label}</b>", ParagraphStyle("al", parent=S["body"], textColor=fg)),
                Paragraph(_text(text), ParagraphStyle("at", parent=S["body"], textColor=INK))]],
              colWidths=[20 * mm, BODY_W - 20 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3, fg),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _band(cells, cols=3):
    """Summary figures: label / value / sub, in a light box."""
    w = BODY_W / cols
    grid, row = [], []
    for lab, val, sub in cells:
        row.append([Paragraph(_text(lab), S["lab"]), Paragraph(_text(val), S["val"]),
                    Paragraph(_text(sub), S["small"])])
        if len(row) == cols:
            grid.append(row)
            row = []
    if row:
        grid.append(row + [""] * (cols - len(row)))
    t = Table(grid, colWidths=[w] * cols)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _chart(rs, start_day: date, target_g: float, width=BODY_W, height=62 * mm):
    """Weight over drying days with the target as a dashed line."""
    pts = [((d - start_day).days, g) for d, g in rs]
    xmax = max(max(x for x, _ in pts), 1)
    lo = min(target_g, min(g for _, g in pts)) * 0.97
    hi = max(g for _, g in pts) * 1.02
    dr = Drawing(width, height)
    lp = LinePlot()
    lp.x, lp.y = 38, 22
    lp.width, lp.height = width - 50, height - 34
    lp.data = [pts]
    lp.lines[0].strokeColor = RED
    lp.lines[0].strokeWidth = 1.4
    lp.lines[0].symbol = makeMarker("FilledCircle", size=3.2, fillColor=RED, strokeColor=RED)
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0, xmax
    lp.xValueAxis.labels.fontName = lp.yValueAxis.labels.fontName = "DejaVu"
    lp.xValueAxis.labels.fontSize = lp.yValueAxis.labels.fontSize = 7
    lp.xValueAxis.labelTextFormat = lambda v: f"{start_day + timedelta(days=round(v)):%d %b}"
    lp.xValueAxis.strokeColor = lp.yValueAxis.strokeColor = MUTED
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = lo, hi
    lp.yValueAxis.labelTextFormat = lambda v: f"{v:.0f} g"
    lp.yValueAxis.visibleGrid = True
    lp.yValueAxis.gridStrokeColor = LINE
    dr.add(lp)
    ty = lp.y + (target_g - lo) / (hi - lo) * lp.height
    dr.add(Line(lp.x, ty, lp.x + lp.width, ty, strokeColor=INK, strokeWidth=0.8, strokeDashArray=[4, 3]))
    dr.add(String(lp.x + lp.width - 2, ty + 3, f"target {target_g:.0f} g", fontName="DejaVu",
                  fontSize=7, fillColor=INK, textAnchor="end"))
    dr.add(String(lp.x, lp.y + lp.height + 4, "Weight incl. wrap + net [g], red; dashed: target", fontName="DejaVu-Bold",
                  fontSize=7, fillColor=RED))
    return dr


def _climate_chart(crs, excl, weigh_days, limit_c, width=BODY_W, height=70 * mm):
    """Temperature (left axis, red) and humidity (right axis, green) over the drying period, hourly
    averages, like the app's chart (owner, 31 Oct 2026): dashed limit line, grey left-out periods,
    dotted weigh-ins at 12:00. A line is broken where readings are missing for more than 1.5 h."""
    hrs = sensors.aggregate(crs, 1)
    if not hrs:
        return None
    t0 = hrs[0]["mid"].replace(minute=0)
    t1 = hrs[-1]["mid"]
    span = max((t1 - t0).total_seconds() / 3600, 1)
    temps = [b["t"] for b in hrs if b["t"] is not None] + [limit_c]
    rhs = [b["h"] for b in hrs if b["h"] is not None]
    tlo, thi = min(temps) - 0.3, max(temps) + 0.3
    hlo, hhi = (min(rhs) - 2, max(rhs) + 2) if rhs else (0, 100)
    dr = Drawing(width, height)
    x0, y0, pw, ph = 34, 20, width - 68, height - 34
    X = lambda t: x0 + (t - t0).total_seconds() / 3600 / span * pw
    YT = lambda v: y0 + (v - tlo) / (thi - tlo) * ph
    YH = lambda v: y0 + (v - hlo) / max(hhi - hlo, 1e-9) * ph
    font = dict(fontName="DejaVu", fontSize=7)
    for a, b in excl:                                    # left-out periods
        a, b = max(a, t0), min(b, t1)
        if b > a:
            dr.add(Rect(X(a), y0, X(b) - X(a), ph, fillColor=LINE, strokeColor=None))
    for i in range(6):                                   # grid + both axes' labels
        fy = y0 + ph * i / 5
        dr.add(Line(x0, fy, x0 + pw, fy, strokeColor=LINE, strokeWidth=0.4))
        dr.add(String(x0 - 3, fy - 2.5, f"{tlo + (thi - tlo) * i / 5:.1f}", fillColor=RED, textAnchor="end", **font))
        if rhs:
            dr.add(String(x0 + pw + 3, fy - 2.5, f"{hlo + (hhi - hlo) * i / 5:.0f}", fillColor=GREEN, **font))
    days = (t1.date() - t0.date()).days
    step = 1 if days <= 10 else 7 if days <= 70 else 14
    d = t0.date() + timedelta(days=1)
    while d <= t1.date():                                # date ticks at midnight
        tx = X(datetime.combine(d, datetime.min.time()))
        if (d - t0.date()).days % step == 0 or step == 1:
            dr.add(Line(tx, y0, tx, y0 - 2, strokeColor=MUTED, strokeWidth=0.5))
            dr.add(String(tx, y0 - 9, f"{d:%d %b}", fillColor=MUTED, textAnchor="middle", **font))
        d += timedelta(days=1)
    for wd in weigh_days:                                # weigh-ins at 12:00
        wt = sensors.weigh_in_time(wd)
        if t0 <= wt <= t1:
            dr.add(Line(X(wt), y0, X(wt), y0 + ph, strokeColor=MUTED, strokeWidth=0.5, strokeDashArray=[1, 2]))
    ly = YT(limit_c)
    dr.add(Line(x0, ly, x0 + pw, ly, strokeColor=RED, strokeWidth=0.7, strokeDashArray=[4, 3]))
    dr.add(String(x0 + 2, ly + 2, f"{limit_c:g} °C limit", fillColor=RED, **font))

    def lines(field, Y, colour):
        seg, prev = [], None
        for b in hrs:
            v = b[field]
            if v is None or (prev is not None and (b["mid"] - prev).total_seconds() > 1.5 * 3600):
                if len(seg) >= 4:
                    dr.add(PolyLine(seg, strokeColor=colour, strokeWidth=0.8))
                seg = []
            if v is not None:
                seg += [X(b["mid"]), Y(v)]
                prev = b["mid"]
        if len(seg) >= 4:
            dr.add(PolyLine(seg, strokeColor=colour, strokeWidth=0.8))
    if rhs:
        lines("h", YH, GREEN)
    lines("t", YT, RED)
    dr.add(String(x0, y0 + ph + 5, "Temperature [°C], left, red", fillColor=RED, fontName="DejaVu-Bold", fontSize=7))
    if rhs:
        dr.add(String(x0 + pw, y0 + ph + 5, "Humidity [%], right, green", fillColor=GREEN, fontName="DejaVu-Bold",
                      fontSize=7, textAnchor="end"))
    return dr


PHOTO_STEP = {"spice": "Day 0", "cure": "Cure", "dry": "Drying", "equalise": "Equalise"}


def _photo_4x3(path, width):
    """The photo cropped to 4:3 around its centre, so every photo in a grid has the same size."""
    from PIL import Image as PImage, ImageOps
    with PImage.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        if w / h > 4 / 3:
            nw = int(h * 4 / 3)
            im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = int(w * 3 / 4)
            im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        im.thumbnail((900, 675))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    buf.seek(0)
    return Image(buf, width=width, height=width * 3 / 4)


def _photo_grid(rows, cols=3, overflow=None):
    overflow = [] if overflow is None else overflow
    cell_w = BODY_W / cols - 4
    cells, out = [], []
    for r in rows:
        f = storage.photo_file(r["path"])
        step = PHOTO_STEP.get(r["stage"], "Other")
        caption = _cell_text(r["caption"], f"Photo caption ({step}, {_fd(r['taken_at'])})", overflow)
        cap = Paragraph(f"<b>{step}</b> · " + _text(_fd(r["taken_at"]) + (f", {caption}" if caption else "")),
                        S["small"])
        try:
            cells.append([_photo_4x3(f, cell_w - 4), cap])
        except Exception:                      # missing or unreadable: say so, don't fail the report
            cells.append([Paragraph("Photo file missing or unreadable", S["small"]), cap])
    for i in range(0, len(cells), cols):
        row = cells[i:i + cols]
        row += [""] * (cols - len(row))
        out.append(row)
    t = Table(out, colWidths=[BODY_W / cols] * cols)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
    return t


def build_pdf(con, pid: int) -> bytes:
    p = db.project(con, pid)
    closed = p["status"] == "closed"
    today = db.today()
    lines = db.ingredient_lines(con, pid)
    rs = db.readings(con, pid)
    rrows = db.reading_rows(con, pid)
    story = []

    # --- title --------------------------------------------------------------------------- #
    kind = db.chamber_kind(con, p)
    status = f"Closed {_fd(p['closed_at'])}" if closed else f"In progress: summary so far, {_fd(today)}"
    sensor = None
    if p["chamber_id"]:
        sensor = con.execute("SELECT tapo_name FROM chamber WHERE id=?", (p["chamber_id"],)).fetchone()[0]
    story.append(Paragraph("BRESAOLA TRACKER · BATCH REPORT", S["kicker"]))
    story.append(Spacer(1, 2))
    story.append(Paragraph(_text(db.display_name(p)), S["title"]))
    story.append(HRFlowable(width="100%", thickness=1.4, color=RED, spaceBefore=4, spaceAfter=6))
    facts = [("Blend", p["blend"]), ("Raw meat after trimming", f"{p['green_weight_g']:.0f} g"),
             ("Curing salt", "EcoCure #2" if p["ecocure"] else "none"), ("Day 0", _fd(p["start_date"])),
             ("Drying place", safety.KINDS[kind].lower() if kind else "–"), ("Sensor", sensor or "–"),
             ("Status", status), ("Report", f"generated {_fd(today)}, app v{__version__}")]
    lab = ParagraphStyle("fl", parent=S["lab"])
    cells = [[Paragraph(_text(a), lab), Paragraph(_text(b), S["cell"])] for a, b in facts]
    grid = [cells[i] + cells[i + 1] for i in range(0, len(cells), 2)]
    ft = Table(grid, colWidths=[32 * mm, BODY_W / 2 - 32 * mm, 32 * mm, BODY_W / 2 - 32 * mm])
    ft.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [ft, Spacer(1, 8)]
    if not p["ecocure"]:
        dry_rows = (db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"])
                    if p["chamber_id"] and p["dry_start"] else [])
        level, text = safety.no_cure_message(kind, dry_rows)
        story.append(_alert(text, level))
    story.append(Spacer(1, 4))

    # --- 1 result ------------------------------------------------------------------------ #
    story += _h2(1, "Result")
    tare = p["tare_g"] or 0
    cure_days = (_d(p["cure_end_actual"]) - _d(p["cure_start"])).days \
        if p["cure_end_actual"] and p["cure_start"] else None
    if p["dry_start"] and rs:
        final_g = rs[-1][1]
        end = _d(p["dry_end"]) or today
        dry_days = (end - _d(p["dry_start"])).days
        total_days = (end - _d(p["start_date"])).days
        lost = p["dry_start_gross_g"] - final_g
        story.append(_band([
            ("Final weight" if p["dry_end"] else "Weight now", f"{final_g:.0f} g", "last weigh-in, incl. wrap + net"),
            ("Lost while drying", f"{lost:.0f} g",
             f"{calc.loss_pct(p['dry_start_gross_g'], final_g, tare):.1f} % of the meat at the start of drying"),
            ("Final ÷ raw meat" if p["dry_end"] else "Now ÷ raw meat",
             f"{100 * (final_g - tare) / p['green_weight_g']:.0f} %",
             f"meat only, without wrap + net; raw {p['green_weight_g']:.0f} g"),
            ("Cure", f"{cure_days} days" if cure_days is not None else "–", "in the bag"),
            ("Drying", f"{dry_days} days", "wrapped and netted" if p["dry_end"] else "so far"),
            ("Total", f"{total_days} days", "from day 0"),
        ]))
        if p["dry_end"] and (short := db.below_target(con, pid)):
            story.append(Spacer(1, 4))
            story.append(_alert(safety.below_target_message(*short)))
    else:
        story.append(Paragraph("Drying has not started yet, so there is no result.", S["body"]))

    # --- timeline ------------------------------------------------------------------------ #
    story += _h2(2, "Timeline")
    planned = _d(p["cure_end_planned"])
    tl = [["Step", "Date", "Detail"],
          ["Day 0: trimmed, spiced", _fd(p["start_date"]), ""],
          ["Into the bag", _fd(p["cure_start"]), ""],
          ["Planned out of the bag", _fd(planned),
           f"{calc.cure_days(p['thickness_cm'], p['shape'])} days" if p["thickness_cm"] else ""],
          ["Out of the bag", _fd(p["cure_end_actual"]), f"{cure_days} days in the bag" if cure_days is not None else ""],
          ["Drying started", _fd(p["dry_start"]),
           f"{p['dry_start_gross_g']:.0f} g incl. wrap + net" if p["dry_start_gross_g"] else ""],
          ["Drying ended", _fd(p["dry_end"]), ""]]
    if closed:
        tl.append(["Closed", _fd(p["closed_at"]), ""])
    story.append(_table(tl, [60 * mm, 40 * mm, BODY_W - 100 * mm]))

    overflow: list[tuple[str, str]] = []      # long cell texts, printed in full at the end of their section

    def full_texts():
        """Long table texts of this section, in full (they can't split across pages inside a cell)."""
        for k, v in overflow:
            story.append(Paragraph(f"<b>{_text(k)}</b>", ParagraphStyle("nh", parent=S["body"], keepWithNext=1)))
            story.extend(Paragraph(_text(part), S["body"]) for part in v.split("\n\n"))
            story.append(Spacer(1, 4))
        overflow.clear()
    allp = db.photos(con, pid)

    def photos_for(stages, title):
        """Each step's photos at the end of its own section (owner, 1 Nov 2026)."""
        rows = sorted((r for r in allp if r["stage"] in stages), key=lambda r: r["taken_at"])
        if rows:
            story.append(Paragraph(title, S["h3"]))
            story.append(_photo_grid(rows, overflow=overflow))

    # --- recipe -------------------------------------------------------------------------- #
    story += _h2(3, "Day 0: recipe and spice mix")
    rows = [["Ingredient", "Rate", "Plan", "Actual", "Note"]]
    for l in lines:
        pct = l["unit"] == "pct"
        rate = f"{l['rate'] * 100:.3g} %" if pct else f"{l['rate']:g} pcs/kg"
        fmt = (lambda v: f"{v:.1f} g") if pct else (lambda v: f"{v:.0f} pcs")
        rows.append([l["name"], rate, fmt(l["planned"]),
                     fmt(l["actual"]) if l["actual"] is not None else "–",
                     _cell_text(l["note"], f"Ingredient note: {l['name']}", overflow)])
    story.append(_table(_right(rows, (1, 2, 3)), [52 * mm, 22 * mm, 20 * mm, 20 * mm, BODY_W - 114 * mm]))
    plan_mix = calc.mix_summary([(l["name"], l["unit"], l["planned"]) for l in lines], p["green_weight_g"])
    act_mix = calc.mix_summary([(l["name"], l["unit"], l["actual"]) for l in lines], p["green_weight_g"])
    weighed = [l for l in lines if l["unit"] == "pct"]
    summary = (f"Total weighed: plan {sum(l['planned'] for l in weighed):.1f} g, actual "
               f"{sum(l['actual'] or 0 for l in weighed):.1f} g. Salt {act_mix.salt_pct:.1f} % of meat "
               f"(plan {plan_mix.salt_pct:.1f} %)"
               + (f", EcoCure {act_mix.ecocure_pct:.1f} %" if p["ecocure"] else "")
               + f", sugar {act_mix.sugar_pct:.1f} %, spices {act_mix.seasoning_pct:.1f} %.")
    story.append(Spacer(1, 3))
    story.append(Paragraph(_text(summary), S["small"]))

    story += _notes("Notes: Day 0", p["spice_note"])
    photos_for({"spice"}, "Photos: Day 0")
    full_texts()

    # --- cure ---------------------------------------------------------------------------- #
    if p["thickness_cm"]:
        story += _h2(4, "Cure")
        est = " (estimate)" if p["thickness_estimated"] else ""
        mins = calc.cure_days_minimum(p["thickness_cm"], p["shape"])
        story.append(Paragraph(_text(
            f"Equilibrium cure in a vacuum bag. Piece: {p['shape']}, {p['thickness_cm']:g} cm thick{est}"
            + (f", {p['length_cm']:g} cm long" if p["length_cm"] else "")
            + f". Calculator minimum {mins:.1f} days + 20 % = {calc.cure_days(p['thickness_cm'], p['shape'])} days"
            + (f"; actual {cure_days} days." if cure_days is not None else ".")
            + (f" Cure fridge {p['cure_fridge_c']:g} °C." if p["cure_fridge_c"] is not None else "")), S["body"]))
        length = db.cure_length(p)
        if length == "below_min":
            confirmed = any(e["kind"] == "cure_locked" and "below calculator minimum" in (e["detail"] or "")
                            for e in db.events(con, pid))
            story.append(_alert(f"The cure ({cure_days} days) was shorter than the calculator minimum "
                                f"({mins:.1f} days): the salt may not have reached the centre."
                                + (" Locked anyway, confirmed by the maker." if confirmed else "")))
        elif length == "short":
            story.append(Paragraph(_text(f"The cure was past the calculator minimum but short of the planned "
                                         f"{calc.cure_days(p['thickness_cm'], p['shape'])} days (20 % margin)."),
                                   S["small"]))
        if w := safety.cure_fridge_warning(p["cure_fridge_c"]):
            story.append(_alert(w))

    if p["thickness_cm"]:
        story += _notes("Notes: Cure", p["cure_note"])
    photos_for({"cure"}, "Photos: Cure")
    full_texts()

    # --- drying -------------------------------------------------------------------------- #
    if p["dry_start"] and rs:
        s = db.drying_status(con, pid)
        story.append(PageBreak())
        head = _h2(5, "Drying")
        ch = con.execute("SELECT name, tapo_name FROM chamber WHERE id=?", (p["chamber_id"],)).fetchone() \
            if p["chamber_id"] else None
        head.append(Paragraph(_text(
            f"Target {p['target_loss_pct']:g} % weight loss on the meat at the start of drying (start weight "
            f"minus packaging) = {s['target_gross_g']:.0f} g incl. wrap + net. "
            f"Packaging (wrap + net) {tare:.0f} g{' (estimate)' if p['tare_estimated'] else ''}."
            + (f" Dried in a {safety.KINDS[kind or 'fridge'].lower()}"
               + (f", sensor {ch['tapo_name']}" if ch["tapo_name"] else "") + "." if ch else "")), S["body"]))
        head += [Spacer(1, 4), _chart(rs, _d(p["dry_start"]), s["target_gross_g"])]
        story.append(KeepTogether(head))
        crs = db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"]) if p["chamber_id"] else []
        match = sensors.day_averages([_d(r["day"]) for r in rrows], crs)
        per = sensors.period_averages([_d(r["day"]) for r in rrows], crs)

        def cell(m, i, unit=""):
            if not m or m[i] is None:
                return "–"
            flag = " ⚠" if safety.out_of_range("t" if i == 0 else "h", m[i], kind or "fridge") else ""
            return (f"{m[i]:.1f}" if i == 0 else f"{m[i]:.0f}") + unit + ("*" if m[3] else "") + flag
        wr = [["Date", "Day", "Weight", "Lost", "Day °C", "Day RH", "Since °C", "Since RH", "Data", "Note"]]
        for r in rrows:
            day = _d(r["day"])
            m, q = match.get(day), per.get(day)
            wr.append([_fd(day), str((day - _d(p["dry_start"])).days), f"{r['gross_g']:.0f} g",
                       f"{calc.loss_pct(p['dry_start_gross_g'], r['gross_g'], tare):.1f} %",
                       cell(m, 0), cell(m, 1, " %"), cell(q, 0), cell(q, 1, " %"),
                       f"{q[4] * 100:.0f} %" if q else "–",
                       _cell_text(r["note"], f"Weigh-in note, {_fd(day)}", overflow)])
        story.append(_table(_right(wr, (1, 2, 3, 4, 5, 6, 7, 8)),
                            [22 * mm, 10 * mm, 17 * mm, 14 * mm, 14 * mm, 14 * mm, 15 * mm, 15 * mm, 12 * mm,
                             BODY_W - 133 * mm]))
        if crs:
            story.append(Paragraph("Day: average of all chamber readings on the weigh-in day. Since: average since "
                                   "the previous weigh-in (12:00 to 12:00), the conditions behind that weight loss; "
                                   "Data = share of those hours with sensor readings. * less than half the time "
                                   "covered; – no readings; ⚠ outside the safe range for a "
                                   f"{safety.KINDS[kind or 'fridge'].lower()} (above {safety.TEMP_MAX[kind or 'fridge']:g} °C, "
                                   f"humidity outside {safety.RH_MIN:g}-{safety.RH_MAX:g} %).", S["small"]))
        if crs:                                # the sensor chart, as in the app (owner, 31 Oct 2026)
            excl = [(datetime.fromisoformat(e["start_ts"]), datetime.fromisoformat(e["end_ts"]))
                    for e in db.exclusions(con, p["chamber_id"])]
            cc = _climate_chart(crs, excl, [_d(r["day"]) for r in rrows], safety.TEMP_MAX[kind or "fridge"])
            if cc is not None:
                story.append(KeepTogether([Spacer(1, 6), Paragraph("Temperature and humidity during drying",
                                                                   S["h3"]), cc,
                                           Paragraph("Hourly averages. Dashed red line: the "
                                                     f"{safety.TEMP_MAX[kind or 'fridge']:g} °C limit. Grey: left-out "
                                                     "periods. Dotted lines: weigh-ins (12:00). Breaks in a line: no "
                                                     "readings for more than 1.5 h.", S["small"])]))
        if p["chamber_id"]:
            cr = db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"] or today.isoformat())
            temps = [r["temp_c"] for r in cr if r["temp_c"] is not None]
            rhs = [r["rh_pct"] for r in cr if r["rh_pct"] is not None]
            if temps or rhs:
                bits = []
                if temps:
                    bits.append(f"temperature {min(temps):.1f} to {max(temps):.1f} °C (average {sum(temps)/len(temps):.1f})")
                if rhs:
                    bits.append(f"humidity {min(rhs):.0f} to {max(rhs):.0f} % (average {sum(rhs)/len(rhs):.0f})")
                story.append(Spacer(1, 3))
                story.append(Paragraph(_text(f"Chamber during drying ({len(cr)} readings): " + "; ".join(bits) + "."),
                                       S["small"]))
            warns, notes_ = safety.chamber_warnings(cr, kind or "fridge")
            for w in warns:
                story.append(Spacer(1, 3))
                story.append(_alert(w))
            for n in notes_:
                story.append(Paragraph(_text(n), S["small"]))
        if w := safety.target_message(float(p["target_loss_pct"]), hint=False):
            story.append(Spacer(1, 3))
            story.append(_alert(w))

    if p["dry_start"] and rs:
        story += _notes("Notes: Drying", p["dry_note"])
    photos_for({"dry"}, "Photos: Drying")
    full_texts()

    # --- 6 finish: final notes and photos without a step ------------------------------------ #
    fin = [r for r in allp if r["stage"] in ("equalise", None)]
    if (p["final_notes"] or "").strip() or fin:
        story += _h2(6, "Finish")
        story += _notes("Final notes", p["final_notes"])
        photos_for({"equalise", None}, "Photos: Finish")
        full_texts()

    # --- build --------------------------------------------------------------------------- #
    name = db.display_name(p)

    class PagedCanvas(rl_canvas.Canvas):
        """Header from page 2, footer with 'page x of y' (needs all pages first: drawn at save)."""
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.saveState()
                self.setFont("DejaVu", 7)
                self.setFillColor(MUTED)
                self.setStrokeColor(LINE)
                if self._pageNumber > 1:
                    self.drawString(MARGIN, PAGE_H - 10 * mm, f"Batch report · {name}")
                    self.line(MARGIN, PAGE_H - 11.5 * mm, PAGE_W - MARGIN, PAGE_H - 11.5 * mm)
                self.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
                self.drawString(MARGIN, 9 * mm, f"Bresaola Tracker v{__version__} · {name} · generated {_fd(today)}")
                self.drawRightString(PAGE_W - MARGIN, 9 * mm, f"page {self._pageNumber} of {total}")
                self.restoreState()
                super().showPage()
            super().save()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN + 2 * mm, bottomMargin=18 * mm,
                            title=f"Bresaola: {name}", author="Bresaola Tracker")
    doc.build(story, canvasmaker=PagedCanvas)
    return buf.getvalue()


def build_pdf_standalone(pid: int) -> bytes:
    """For Streamlit's download button, which builds the file in another thread.
    SQLite connections belong to the thread that opened them, so open a fresh one here."""
    con = db.connect(storage.db_path())
    try:
        return build_pdf(con, pid)
    finally:
        con.close()


def file_name(p) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in p["name"]).strip("-")
    return f"bresaola-{(p['start_date'] or '')[:10]}-{safe}.pdf"
