"""Deployment files (NAS / Docker)."""
import re
from pathlib import Path

from bresaola import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_compose_image_tag_is_the_app_version():
    """With a fixed image name, Container Manager's Build reused the old image and the NAS stayed on
    v0.4.1 after an update (27 Oct 2026). A tag per version forces a real build."""
    tag = re.search(r"^\s*image:\s*bresaola-tracker:(\S+)", (ROOT / "compose.yaml").read_text(), re.M)
    assert tag and tag.group(1) == __version__
