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
    return " ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def jpeg():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (800, 600), "brown").save(b, "JPEG")
    return b.getvalue()


def test_demo_summary_contents(con):
    t = text(report.build_pdf(con, 1))
    for s in ("26/08/15 Palermo Spicy", "summary so far", "1963 g", "137 g", "36 days",
              "Fennel seed, powder", "Used less fennel than planned", "Timeline", "18 Sep 2026",
              "1365 g", "8 Oct 2026", "Equilibrium dry cure", "Fridge drawer"):
        assert s in t, s


def test_closed_summary_and_final_notes(con):
    with con:
        db.lock_dry(con, 1, date(2026, 10, 8))
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
    assert sum(len(p.images) for p in PdfReader(io.BytesIO(pdf)).pages) == 1


def test_new_project_without_any_data(con):
    pid = db.create_project(con, "Fresh", "Classic Italian", False, 1500, start_date=TODAY)
    t = text(report.build_pdf(con, pid))
    assert "Drying has not started yet" in t and "Recipe" in t


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
