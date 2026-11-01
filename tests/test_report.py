"""PDF summary."""
import io
from datetime import date, datetime
from pathlib import Path

import pytest
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from bresaola import db, report, storage
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")
TODAY = date(2026, 10, 12)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setattr(db, "today", lambda: TODAY)
    monkeypatch.setattr(db, "now_local", lambda: datetime(2026, 10, 12, 12, 0, tzinfo=db.TZ))  # closing timestamp
    c = db.connect(storage.db_path())
    seed_demo(c)
    return c


def text(pdf: bytes) -> str:
    return " ".join(" ".join(page.extract_text().replace("\xa0", " ").split()) for page in PdfReader(io.BytesIO(pdf)).pages)


def jpeg():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (800, 600), "brown").save(b, "JPEG")
    return b.getvalue()


def test_demo_summary_contents(con):
    t = text(report.build_pdf(con, 1))
    for s in ("Palermo Spicy (15-Aug-26)", "summary so far", "1963 g", "137 g", "36 days",
              "Fennel seed, powder", "Used less fennel than planned", "Timeline", "18 Sep 2026",
              "1365 g", "8 Oct 2026", "Equilibrium dry cure", "Dried in a fridge"):
        assert s in t, s


def test_closed_summary_and_final_notes(con):
    with con:
        db.lock_dry(con, 1, date(2026, 10, 8), below_target_ok=True)
        db.close_project(con, 1, "Firm, sweet, a bit salty. Next time 2.8 % salt & < 35 % loss")
    t = text(report.build_pdf(con, 1))
    assert "Closed 12 Oct 2026" in t and "summary so far" not in t
    assert "Final weight" in t and "Final notes" in t and "2.8 % salt & < 35 % loss" in t


def test_photos_included_and_missing_file_tolerated(con):
    with con:
        db.add_photo(con, 1, storage.save_photo(1, "a.jpg", jpeg()), "2026-08-15", "rub", stage="spice")
        db.add_photo(con, 1, "photos/1/gone.jpg", "2026-09-20", "lost file", stage="cure")
    pdf = report.build_pdf(con, 1)
    t = text(pdf)
    assert "Photos" in t and "rub" in t and "missing or unreadable" in t
    r = PdfReader(io.BytesIO(pdf))
    assert sum(len(p.images) for p in r.pages) == 1            # once, in its own section; no appendix
    assert not list(r.attachments) and "Appendix" not in t     # owner, 1 Nov 2026: no full-size copies
    assert t.index("3 Day 0: recipe and spice mix") < t.index("Photos: Day 0") < t.index("4 Cure") < t.index("Photos: Cure") < t.index("5 Drying")


def test_climate_chart_in_pdf(con):
    """Owner, 31 Oct 2026: the PDF lacked the temperature and humidity chart."""
    from datetime import datetime, timedelta
    from bresaola import sensors
    with con:
        sensors.import_readings(con, 1, [(datetime(2026, 9, 21) + timedelta(minutes=15 * i), 2.0 + (i % 40) / 20,
                                          80.0) for i in range(4 * 24 * 10)], "tapo_export")
        db.add_exclusion(con, 1, datetime(2026, 9, 24), datetime(2026, 9, 25))
    t = text(report.build_pdf(con, 1))
    assert "Temperature and humidity during drying" in t
    assert "4 °C limit" in t and "Temperature [°C], left, red" in t and "Humidity [%], right, green" in t


def test_no_climate_chart_without_readings(con):
    assert "Temperature and humidity during drying" not in text(report.build_pdf(con, 1))


def test_new_project_without_any_data(con):
    pid = db.create_project(con, "Fresh", "Classic Italian", False, 1500, start_date=TODAY)
    t = text(report.build_pdf(con, pid))
    assert "Drying has not started yet" in t and "recipe and spice mix" in t


def test_file_name_is_safe(con):
    db.rename_project(con, 1, "Palermo / Spicy: v2")
    assert report.file_name(db.project(con, 1)) == "bresaola-2026-08-15-Palermo---Spicy--v2.pdf"


def test_finish_offers_the_pdf(con, monkeypatch):
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "rail_finish").click()
    at.run()
    assert not at.exception, at.exception
    labels = [e.proto.label for e in at.get("download_button")]
    assert "Download summary so far (PDF)" in labels


def test_pdf_can_be_built_from_another_thread(con):
    """Streamlit's download button runs the builder in a worker thread (bug found in v0.3.8 testing)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as ex:
        pdf = ex.submit(report.build_pdf_standalone, 1).result()
    assert pdf.startswith(b"%PDF")


def test_professional_layout(con):
    """Owner, 1 Nov 2026: title block, numbered sections, each step's notes in its own section,
    running header, 'page x of y'."""
    with con:
        db.set_dry_note(con, 1, "turned the piece")
    pdf = report.build_pdf(con, 1)
    t = text(pdf)
    pages = PdfReader(io.BytesIO(pdf)).pages
    assert "BRESAOLA TRACKER · BATCH REPORT" in t and "Drying place" in t and "Sensor" in t
    for i, h in enumerate(["1 Result", "2 Timeline", "3 Day 0", "4 Cure", "5 Drying"]):
        assert h in t, h
    assert t.index("5 Drying") < t.index("Notes: Drying") < t.index("turned the piece")
    assert t.index("4 Cure") < t.index("Notes: Cure") < t.index("5 Drying")
    assert f"page 1 of {len(pages)}" in pages[0].extract_text()
    assert "Batch report · Palermo Spicy" in pages[1].extract_text()


def test_cure_note_without_measurements_is_kept(con):
    """Diff audit v0.4.25: cure notes vanished when the batch had no cure thickness."""
    with con:
        con.execute("UPDATE project SET thickness_cm=NULL, cure_note='CURENOTE_X' WHERE id=1")
    t = text(report.build_pdf(con, 1))
    assert "4 Cure" in t and "CURENOTE_X" in t


def test_dry_note_without_weigh_ins_is_kept(con):
    """Diff audit v0.4.25: drying notes vanished when drying had started without weigh-ins."""
    with con:
        con.execute("DELETE FROM reading WHERE project_id=1")
        con.execute("UPDATE project SET dry_note='DRYNOTE_X' WHERE id=1")
    t = text(report.build_pdf(con, 1))
    assert "DRYNOTE_X" in t and "no weigh-ins yet" in t and "Drying has not started yet" not in t


def test_weight_chart_ticks_whole_days():
    """Diff audit v0.4.25: short batches showed the same date on several ticks."""
    from datetime import date
    for n in (1, 2, 3, 40):
        from datetime import timedelta
        dr = report._chart([(date(2026, 9, 1), 2000), (date(2026, 9, 1) + timedelta(days=n), 1990)], date(2026, 9, 1), 1300)
        lp = dr.contents[0]
        assert all(float(v).is_integer() for v in lp.xValueAxis.valueSteps)
