"""Photos are made upright, shrunk and stripped of metadata on upload."""
import io

import pytest
from PIL import Image

from bresaola import storage


def jpeg(w, h, orientation=None, colour="brown"):
    im = Image.new("RGB", (w, h), colour)
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    exif[0x8825] = {2: (52, 0, 0)}           # a GPS tag that must not survive
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95, exif=exif)
    return buf.getvalue()


def test_phone_photo_is_shrunk_to_1600px(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    import random
    big = Image.effect_noise((4000, 3000), 60).convert("RGB")   # noisy like a real photo
    buf = io.BytesIO(); big.save(buf, "JPEG", quality=95); raw = buf.getvalue()
    rel = storage.save_photo(1, "IMG_1234.jpg", raw)
    f = storage.photo_file(rel)
    im = Image.open(f)
    assert max(im.size) == storage.PHOTO_MAX_PX and im.format == "JPEG"
    assert f.stat().st_size < len(raw) / 3


def test_orientation_applied_and_metadata_removed():
    out = Image.open(io.BytesIO(storage.shrink_image(jpeg(400, 200, orientation=6))))
    assert out.size == (200, 400)              # rotated upright
    assert not out.getexif()                   # no GPS, no orientation left behind


def test_png_with_transparency_becomes_jpeg():
    im = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    buf = io.BytesIO(); im.save(buf, "PNG")
    out = Image.open(io.BytesIO(storage.shrink_image(buf.getvalue())))
    assert out.format == "JPEG" and out.getpixel((10, 10)) == (255, 255, 255)


def test_not_a_photo_is_refused():
    with pytest.raises(ValueError, match="not a photo"):
        storage.shrink_image(b"%PDF-1.4 hello")


def test_heic_is_accepted():
    pytest.importorskip("pillow_heif")
    im = Image.new("RGB", (2000, 1500), "brown")
    buf = io.BytesIO(); im.save(buf, "HEIF")
    out = Image.open(io.BytesIO(storage.shrink_image(buf.getvalue())))
    assert out.format == "JPEG" and max(out.size) == 1600


def test_existing_big_photos_shrunk_once(tmp_path, monkeypatch):
    monkeypatch.setenv("BRESAOLA_DATA", str(tmp_path))
    f = storage.data_dir() / "photos" / "1" / "old.jpg"
    f.parent.mkdir(parents=True)
    big = Image.effect_noise((4000, 3000), 60).convert("RGB")
    big.save(f, "JPEG", quality=95)
    assert storage.shrink_existing_photos() == 1
    assert max(Image.open(f).size) == 1600
    assert storage.shrink_existing_photos() == 0          # already small: untouched
