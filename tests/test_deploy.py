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


def test_tapo_settings_come_from_env_file_not_compose():
    """Updates replace compose.yaml (and nightly auto-updates reset it): secrets live in .env."""
    c = (ROOT / "compose.yaml").read_text()
    for k in ("TAPO_USERNAME", "TAPO_PASSWORD", "TAPO_HUB_IP", "TAPO_SENSORS"):
        assert re.search(rf"^\s*{k}: \$\{{{k}:-\}}\s*$", c, re.M), k


def test_secrets_stay_out_of_git_and_image():
    for f in (".gitignore", ".dockerignore"):
        lines = (ROOT / f).read_text().split()
        assert ".env" in lines and "deploy_key.pub" in lines and "data/" in lines, f
