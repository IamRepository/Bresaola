"""Full-audit findings (26 Oct 2026) fixed in v0.4.8: the owner's list 14-19
(audit #12, #16, #14, #18, #19, #20). Each failed before the fix."""
import io
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from bresaola import db, storage, tapo_sync
from bresaola.demo import seed_demo
from tests.test_sensors import FakeSensor, fake_factory

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
TODAY = date(2026, 10, 11)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    monkeypatch.setenv("BRESAOLA_MODE", "persistent")
    monkeypatch.setattr(db, "today", lambda: TODAY)
    con = db.connect(storage.db_path())
    seed_demo(con)
    return con


def start(step=None):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    if step:
        next(b for b in at.button if b.key == f"rail_{step}").click()
        at.run()
        assert not at.exception, at.exception
    return at


def jpeg():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 30), "brown").save(b, "JPEG")
    return b.getvalue()


# 14 (audit #12): a chamber name with <...> is shown as typed, not as HTML
def test_chamber_name_is_not_html(env):
    """Since v0.4.17 the section title shows the batch's Tapo sensor name: still plain text."""
    with env:
        env.execute("UPDATE chamber SET tapo_name='Fridge <b>old</b>' WHERE id=1")
    at = start()
    blocks = [m.value for m in at.markdown if 'class="blk"' in m.value]
    assert any("Tapo sensor Fridge &lt;b&gt;old&lt;/b&gt;" in b for b in blocks), blocks
    assert not any("<b>old</b>" in b for b in blocks)


# 15 (audit #16): a backup whose photo paths point outside data/photos is refused, and such a
# path is never opened
def test_restore_refuses_photo_paths_outside_photos(env, tmp_path):
    with env:
        env.execute("INSERT INTO photo (project_id, taken_at, path, stage) VALUES (1, '2026-08-15', "
                    "'../../etc/passwd', 'spice')")
    env.close()
    bad = storage.make_backup()
    before = (tmp_path / storage.DB_NAME).read_bytes()
    with pytest.raises(ValueError, match="outside the photos folder"):
        storage.restore_backup(bad)
    assert (tmp_path / storage.DB_NAME).read_bytes() == before


def test_normal_backup_still_restores(env, tmp_path):
    with env:
        db.add_photo(env, 1, storage.save_photo(1, "a.jpg", jpeg()), "2026-08-15", "rub", stage="spice")
    env.close()
    storage.restore_backup(storage.make_backup())


def test_photo_path_outside_photos_is_never_opened(env, tmp_path):
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(jpeg())
    assert not storage.photo_file("secret.jpg").exists()
    assert not storage.photo_file("photos/../secret.jpg").exists()
    assert not storage.photo_file(str(secret)).exists()
    rel = storage.save_photo(1, "a.jpg", jpeg())
    assert storage.photo_file(rel).is_file()


# 16 (audit #14): names with Markdown characters show exactly as typed
def test_project_name_with_markdown_characters(env):
    with env:
        db.rename_project(env, 1, "My_test_batch *2*")
    at = start()
    assert at.header[0].value.endswith(r"My\_test\_batch \*2\*")
    label = next(t.label for t in at.sidebar.text_input if t.key == "del1")
    assert r"**My\_test\_batch \*2\***" in label


# 17 (audit #18): a deleted project's number is never given to a new one
def test_project_ids_not_reused(env):
    pid = db.create_project(env, "Temp", "Classic Italian", False, 1000, start_date=TODAY)
    with env:
        db.delete_project(env, pid)
    new = db.create_project(env, "Next", "Classic Italian", False, 1000, start_date=TODAY)
    assert new > pid


def test_ids_not_reused_after_upgrade_from_old_database(env, tmp_path):
    pid = db.create_project(env, "Temp", "Classic Italian", False, 1000, start_date=TODAY)
    with env:
        env.execute("DROP TABLE meta")                         # as in a v0.4.7 database
    env.close()
    con = db.connect(storage.db_path())                       # upgrade: remembers the current top id
    with con:
        db.delete_project(con, pid)
    assert db.create_project(con, "Next", "Classic Italian", False, 1000, start_date=TODAY) > pid


# 18 (audit #19): chambers nobody uses can be deleted
def test_unused_chamber_can_be_deleted(env):
    with env:
        other = db.get_or_create_chamber(env, "Old cellar")
        env.execute("INSERT INTO chamber_reading (chamber_id, ts, temp_c, source) VALUES (?, '2026-09-01T12:00:00', 9, 'manual')",
                    (other,))
    assert [c["name"] for c in db.unused_chambers(env)] == ["Old cellar"]
    with pytest.raises(ValueError, match="Still used by"):
        db.delete_chamber(env, db.project(env, 1)["chamber_id"])
    with env:
        assert db.delete_chamber(env, other) == 1
    assert db.unused_chambers(env) == []
    assert env.execute("SELECT COUNT(*) FROM chamber_reading WHERE chamber_id=?", (other,)).fetchone()[0] == 0


def test_unused_chamber_deleted_from_the_sidebar(env):
    with env:
        other = db.get_or_create_chamber(env, "Old cellar")
    at = start()
    next(c for c in at.sidebar.checkbox if c.key == f"chdelok{other}").check()
    at.run()
    next(b for b in at.sidebar.button if b.key == f"chdel{other}").click()
    at.run()
    assert not at.exception, at.exception
    assert [c["name"] for c in db.chambers(env)] == ["Fridge drawer"]


# 19 (audit #20): hub sync finds the chamber despite capitals/spaces; never silently makes a new one
@pytest.fixture
def tapo(monkeypatch):
    monkeypatch.setenv("TAPO_USERNAME", "me@example.com")
    monkeypatch.setenv("TAPO_PASSWORD", "secret")
    monkeypatch.setenv("TAPO_HUB_IP", "192.168.1.50")
    return monkeypatch


def test_sync_matches_name_loosely(env, tapo):
    tapo.setenv("TAPO_SENSORS", "  fridge   DRAWER =Bresaola sensor")
    res = tapo_sync.sync(env, fake_factory(FakeSensor()))
    assert res[0].error is None and res[0].stored == 3
    assert [c["name"] for c in db.chambers(env)] == ["Fridge drawer"]


def test_sync_unknown_name_is_an_error_not_a_new_chamber(env, tapo):
    tapo.setenv("TAPO_SENSORS", "Cellar=Bresaola sensor")
    res = tapo_sync.sync(env, fake_factory(FakeSensor()))
    assert "no chamber called 'Cellar'" in res[0].error and "Tapo sensor name in the app" in res[0].error
    assert [c["name"] for c in db.chambers(env)] == ["Fridge drawer"]



# nightly log: no harmless warnings in the mail
def test_quiet_nightly_log():
    script = (ROOT / "scripts" / "nas-update.sh").read_text()
    assert "LogLevel=ERROR" in script and "BUILDX_GIT_INFO=false" in script and "build --quiet" in script
    docker = (ROOT / "Dockerfile").read_text()
    assert "PIP_ROOT_USER_ACTION=ignore" in docker and "PIP_DISABLE_PIP_VERSION_CHECK=1" in docker



# diff audit v0.4.8 (Medium): error messages quoting a name show it as typed
def test_error_message_names_are_escaped(env):
    with env:
        db.rename_project(env, 1, "Batch *one*")
        db.create_project(env, "Batch two", "Classic Italian", False, 1000, start_date=TODAY)
    at = start()                                              # opens on whichever project is first
    field = next(t for t in at.sidebar.text_input if t.label == "New name")
    other = "Batch *one*" if field.value == "Batch two" else "Batch two"
    field.input(other)
    at.run()
    next(b for b in at.sidebar.button if b.label == "Rename").click()
    at.run()
    shown = [e.value for e in at.error]
    assert any("already exists" in e for e in shown), shown
    if "*" in other:
        assert any(r"'Batch \*one\*' already exists" in e for e in shown), shown
