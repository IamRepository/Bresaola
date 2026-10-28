"""v0.4.14 (28 Oct 2026): title, facts and step rail stay at the top (compact); messages come below."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from bresaola import db, storage
from bresaola.demo import seed_demo

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_header_and_rail_in_one_sticky_block_messages_below(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    seed_demo(db.connect(storage.db_path()))
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    src = Path(APP).read_text()
    assert 'div[data-testid="stLayoutWrapper"]:has(> .st-key-rail) {{ position: sticky' in src
    assert "@media (max-width: 700px)" in src                     # phones: scrolls normally
    # order on the page: title and steps first, then the no-curing-salt notice and the next-action card
    texts = []

    def walk(n):
        for c in getattr(n, "children", {}).values():
            v = getattr(c, "value", None)
            if isinstance(v, str):
                texts.append(v)
            walk(c)
    walk(at._tree)
    i_title = next(i for i, t in enumerate(texts) if "Palermo Spicy" in t)
    i_rail = next(i for i, t in enumerate(texts) if 'class="stat' in t)
    i_cure = next(i for i, t in enumerate(texts) if t.startswith("No curing salt"))
    i_weigh = next(i for i, t in enumerate(texts) if "Weigh today" in t)
    assert i_title < i_rail < i_cure < i_weigh


def test_compact_rail_keeps_warning_lines():
    """Diff audit v0.4.14 (Low): hiding every second status line also hid 'ended below target'."""
    src = Path(APP).read_text()
    assert ".st-key-rail .stat .more:not(.due) { display: none; }" in src
