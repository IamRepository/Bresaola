"""PDF summary of one batch: result, timeline, recipe, cure, drying, notes and photos.

build_pdf(con, pid) -> bytes. Works for finished and unfinished batches; an unfinished one
is marked "summary so far". Uses the bundled DejaVu fonts so notes with any accents or
symbols print correctly on every machine.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from . import __version__, calc, db, safety, sensors, storage

FONT_DIR = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")

RED = colors.HexColor("#7a2320")
INK = colors.HexColor("#2e2a28")
MUTED = colors.HexColor("#7d7672")
LINE = colors.HexColor("#e3dedb")
SOFT = colors.HexColor("#f6f3f1")

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
BODY_W = PAGE_W - 2 * MARGIN

S = {
    "title": ParagraphStyle("title", fontName="DejaVu-Bold", fontSize=19, leading=23, textColor=INK),
    "sub": ParagraphStyle("sub", fontName="DejaVu", fontSize=9, leading=12, textColor=MUTED),
    "h2": ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=11.5, leading=15, textColor=RED,
                         spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="DejaVu", fontSize=9, leading=12.5, textColor=INK),
    "small": ParagraphStyle("small", fontName="DejaVu", fontSize=7.5, leading=10, textColor=MUTED),
    "lab": ParagraphStyle("lab", fontName="DejaVu", fontSize=7.5, leading=9.5, textColor=MUTED),
    "val": ParagraphStyle("val", fontName="DejaVu-Bold", fontSize=13, leading=16, textColor=INK),
    "cell": ParagraphStyle("cell", fontName="DejaVu", fontSize=8, leading=10, textColor=INK, alignment=TA_LEFT),
}


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
    the full text for the Notes section."""
    s = s or ""
    if len(s) <= CELL_MAX and s.count("\n") < CELL_LINES:
        return s
    overflow.append((label, s))
    short = " ".join(s[:CELL_MAX].split())                  # line breaks folded into spaces
    short = short.rsplit(" ", 1)[0] if " " in short else short
    return short + " … (full text under Notes)"


def _table(rows, widths, header=True, align_right=()):
    data = [[c if isinstance(c, Paragraph) else Paragraph(_text(str(c)), S["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
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
        style += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, MUTED)]
    for col in align_right:
        style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def _right(rows, cols):
    """Wrap numeric cells so they align right inside Paragraph tables."""
    st = ParagraphStyle("r", parent=S["cell"], alignment=2)
    return [[Paragraph(_text(str(c)), st) if i in cols else c for i, c in enumerate(r)] for r in rows]


WARN = colors.HexColor("#8a5a00")
WARN_BG = colors.HexColor("#fbf1dc")


def _alert(text: str):
    """Amber box for safety warnings."""
    t = Table([[Paragraph("<b>Warning:</b> " + _text(text), ParagraphStyle("w", parent=S["body"], textColor=WARN))]],
              colWidths=[BODY_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WARN_BG), ("BOX", (0, 0), (-1, -1), 0.6, WARN),
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
    lp.xValueAxis.labelTextFormat = lambda v: f"day {v:.0f}"
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
    return dr


PHOTO_STEP = {"spice": "Day 0", "cure": "Cure", "dry": "Drying", "equalise": "Equalise"}


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
            from PIL import Image as PImage
            with PImage.open(f) as im:
                w, h = im.size
            scale = min(cell_w / w, (cell_w * 0.8) / h)
            cells.append([Image(str(f), width=w * scale, height=h * scale), cap])
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
    story.append(Paragraph(_text(db.display_name(p)), S["title"]))
    status = f"Closed {_fd(p['closed_at'])}" if closed else f"In progress: summary so far, {_fd(today)}"
    facts = [p["blend"], f"{p['green_weight_g']:.0f} g raw meat after trimming",
             "EcoCure #2" if p["ecocure"] else "no EcoCure", status]
    story.append(Paragraph(_text(" · ".join(facts)), S["sub"]))
    story.append(Spacer(1, 6))
    kind = db.chamber_kind(con, p)
    if not p["ecocure"]:
        dry_rows = (db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"])
                    if p["chamber_id"] and p["dry_start"] else [])
        level, text = safety.no_cure_message(kind, dry_rows)
        story.append(_alert(text) if level == "warning" else Paragraph(_text(text), S["small"]))
    story.append(Spacer(1, 4))

    # --- result -------------------------------------------------------------------------- #
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
    else:
        story.append(Paragraph("Drying has not started yet, so there is no result.", S["body"]))

    # --- timeline ------------------------------------------------------------------------ #
    story.append(Paragraph("Timeline", S["h2"]))
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

    overflow: list[tuple[str, str]] = []      # long cell texts, printed in full under Notes

    # --- recipe -------------------------------------------------------------------------- #
    story.append(Paragraph("Recipe: spice mix", S["h2"]))
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

    # --- cure ---------------------------------------------------------------------------- #
    if p["thickness_cm"]:
        story.append(Paragraph("Cure", S["h2"]))
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

    # --- drying -------------------------------------------------------------------------- #
    if p["dry_start"] and rs:
        s = db.drying_status(con, pid)
        head = [Paragraph("Drying", S["h2"])]
        ch = con.execute("SELECT name FROM chamber WHERE id=?", (p["chamber_id"],)).fetchone() \
            if p["chamber_id"] else None
        head.append(Paragraph(_text(
            f"Target {p['target_loss_pct']:g} % weight loss on the meat at the start of drying (start weight "
            f"minus packaging) = {s['target_gross_g']:.0f} g incl. wrap + net. "
            f"Packaging (wrap + net) {tare:.0f} g{' (estimate)' if p['tare_estimated'] else ''}."
            + (f" Dried in: {ch['name']} ({safety.KINDS[kind or 'fridge'].lower()})." if ch else "")), S["body"]))
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

    # --- notes --------------------------------------------------------------------------- #
    allp = db.photos(con, pid)
    grid = None
    if allp:                                   # built before Notes, so long captions can go there
        order = {"spice": 0, "cure": 1, "dry": 2, "equalise": 3}
        allp = sorted(allp, key=lambda r: (order.get(r["stage"], 9), r["taken_at"]))
        grid = _photo_grid(allp, overflow=overflow)
    notes = [("Day 0", p["spice_note"]), ("Cure", p["cure_note"]), ("Drying", p["dry_note"]),
             ("Final notes", p["final_notes"])]
    notes = [(k, v) for k, v in notes if v and v.strip()] + overflow
    if notes:
        story.append(Paragraph("Notes", S["h2"]))
        for k, v in notes:
            # heading kept with the start of the note; the note itself may run over pages
            story.append(Paragraph(f"<b>{_text(k)}</b>", ParagraphStyle("nh", parent=S["body"], keepWithNext=1)))
            story += [Paragraph(_text(part), S["body"]) for part in v.split("\n\n")]
            story.append(Spacer(1, 4))

    # --- photos -------------------------------------------------------------------------- #
    if grid is not None:
        story.append(Paragraph("Photos", S["h2"]))
        story.append(grid)

    # --- build --------------------------------------------------------------------------- #
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("DejaVu", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 10 * mm, f"Bresaola Tracker v{__version__} · {db.display_name(p)} · "
                                           f"generated {_fd(today)}")
        canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, f"page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=18 * mm,
                            title=f"Bresaola: {db.display_name(p)}", author="Bresaola Tracker")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
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
