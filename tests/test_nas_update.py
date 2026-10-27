"""scripts/nas-update.sh against a local git repo, with fake docker and curl (no NAS needed)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "nas-update.sh"

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def sh(*a, cwd=None, env=None, check=True):
    return subprocess.run(a, cwd=cwd, env=env, check=check, capture_output=True, text=True)


@pytest.fixture
def nas(tmp_path):
    """origin: a bare repo with a 'stable' branch. app: the NAS folder as extracted from the ZIP."""
    src, origin, app, bin_ = tmp_path / "src", tmp_path / "origin.git", tmp_path / "app", tmp_path / "bin"
    for d in (src, app / "data", bin_):
        d.mkdir(parents=True)
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    (src / "scripts").mkdir()
    shutil.copy(SCRIPT, src / "scripts" / "nas-update.sh")
    (src / "bresaola").mkdir()
    (src / "bresaola" / "__init__.py").write_text('__version__ = "1.0.0"\n')
    (src / "compose.yaml").write_text("services:\n  bresaola:\n    image: bresaola-tracker:1.0.0\n")
    (src / ".gitignore").write_text("data/\n.env\nupdate.log\ndeploy_key.pub\n")
    sh(*g, "init", "-q", "-b", "stable", cwd=src)
    sh(*g, "add", "-A", cwd=src)
    sh(*g, "commit", "-qm", "v1", cwd=src)
    sh("git", "clone", "-q", "--bare", str(src), str(origin))
    shutil.copytree(src, app, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))   # = the ZIP
    (app / "data" / "bresaola.sqlite").write_bytes(b"REAL DATA")
    (app / ".env").write_text("TAPO_PASSWORD=secret\n")
    key = tmp_path / "key"
    key.write_text("k")
    # fakes: docker logs its calls; curl answers unless $FAIL_HEALTH exists
    # docker exec: the database backup "fails" (tests the plain-copy path); the version check prints
    # the checked-out version, or an old one if $STALE exists, or fails if $FAIL_HEALTH exists
    (bin_ / "docker").write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/docker.log\n'
                                 'if [ "$1" = exec ]; then\n'
                                 '  case "$*" in *backup*) exit 1;; esac\n'
                                 f'  [ -f {tmp_path}/FAIL_HEALTH ] && exit 1\n'
                                 f'  [ -f {tmp_path}/STALE ] && {{ echo 0.0.1; exit 0; }}\n'
                                 f'  grep -o "[0-9][0-9.]*" {app}/bresaola/__init__.py | head -1; exit 0\n'
                                 'fi\n[ "$1" = images ] && printf "0.9.0\\n1.0.0\\n1.5.0\\n"\nexit 0\n')
    (bin_ / "curl").write_text(f'#!/bin/sh\n[ -f {tmp_path}/FAIL_HEALTH ] && exit 7\nexit 0\n')
    for f in bin_.iterdir():
        f.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", REPO=str(origin), KEY=str(key), WAIT="1")

    def commit(version):
        (src / "bresaola" / "__init__.py").write_text(f'__version__ = "{version}"\n')
        (src / "compose.yaml").write_text(f"services:\n  bresaola:\n    image: bresaola-tracker:{version}\n")
        sh(*g, "commit", "-qam", f"v{version}", cwd=src)
        sh(*g, "push", "-q", str(origin), "stable", cwd=src)

    def run():
        return sh("sh", str(app / "scripts" / "nas-update.sh"), env=env, check=False)
    return SimpleNas(app, tmp_path, run, commit)


class SimpleNas:
    def __init__(self, app, tmp, run, commit):
        self.app, self.tmp, self.run, self.commit = app, tmp, run, commit

    def version(self):
        return (self.app / "bresaola" / "__init__.py").read_text().split('"')[1]

    def log(self):
        return (self.app / "update.log").read_text()


def test_first_run_turns_zip_folder_into_checkout_and_keeps_data(nas):
    r = nas.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (nas.app / ".git").is_dir()
    assert (nas.app / "data" / "bresaola.sqlite").read_bytes() == b"REAL DATA"
    assert (nas.app / ".env").read_text() == "TAPO_PASSWORD=secret\n"
    assert list((nas.app / "data" / "pre-update").glob("bresaola-*.sqlite"))      # copy before the first deploy
    assert "compose -p bresaola up -d --build" in (nas.tmp / "docker.log").read_text()


def test_nothing_new_does_nothing(nas):
    nas.run()
    (nas.tmp / "docker.log").unlink()
    r = nas.run()
    assert r.returncode == 0 and "up to date" in nas.log()
    assert not (nas.tmp / "docker.log").exists()                                   # no rebuild


def test_new_version_is_deployed(nas):
    nas.run()
    nas.commit("1.1.0")
    r = nas.run()
    assert r.returncode == 0, nas.log()
    assert nas.version() == "1.1.0" and "OK: 1.1.0 is running" in nas.log()
    assert (nas.app / "data" / "bresaola.sqlite").read_bytes() == b"REAL DATA"


def test_failed_start_goes_back_and_is_not_retried(nas):
    nas.run()
    nas.commit("1.2.0")
    (nas.tmp / "FAIL_HEALTH").write_text("")
    r = nas.run()
    assert r.returncode == 1
    assert "going back" in nas.log() and nas.version() == "1.0.0"
    (nas.tmp / "FAIL_HEALTH").unlink()
    (nas.tmp / "docker.log").unlink()
    copies = len(list((nas.app / "data" / "pre-update").glob("bresaola-*.sqlite")))
    r = nas.run()                                               # same bad commit: skipped, no new copy
    assert r.returncode == 1 and "not trying again" in nas.log()
    assert not (nas.tmp / "docker.log").exists()
    assert len(list((nas.app / "data" / "pre-update").glob("bresaola-*.sqlite"))) == copies
    nas.commit("1.2.1")                                         # a fixed version is tried
    assert nas.run().returncode == 0 and nas.version() == "1.2.1"


def test_container_still_on_old_version_counts_as_failure(nas):
    """Diff audit v0.4.7 (Medium): the web server answering didn't prove the new version runs."""
    nas.run()
    nas.commit("1.4.0")
    (nas.tmp / "STALE").write_text("")
    assert nas.run().returncode == 1
    assert "container reports '0.0.1', expected 1.4.0" in nas.log() and nas.version() == "1.0.0"


def test_failed_first_run_is_retried_later(nas):
    """Diff audit v0.4.7 (Medium): a failed first run then said "up to date" forever."""
    (nas.tmp / "FAIL_HEALTH").write_text("")
    assert nas.run().returncode == 1 and "first run" in nas.log()
    r = nas.run()                                    # same commit: still reported as a failure, not "up to date"
    assert r.returncode == 1 and "up to date" not in nas.log()
    (nas.tmp / "FAIL_HEALTH").unlink()
    nas.commit("1.0.1")
    r = nas.run()
    assert r.returncode == 0 and "OK: 1.0.1 is running" in nas.log()


def test_compose_copy_kept_before_update(nas):
    """Diff audit v0.4.7 (Medium): local compose.yaml edits were replaced without a copy."""
    (nas.app / "compose.yaml").write_text("services:\n  bresaola:\n    image: bresaola-tracker:1.0.0\n# mine\n")
    nas.run()
    kept = list((nas.app / "data" / "pre-update").glob("compose-*.yaml"))
    assert kept and "# mine" in kept[0].read_text()


def test_previous_image_is_kept_for_rollback(nas):
    """Diff audit v0.4.7 (Medium): all other image tags were deleted, so a rollback had to rebuild."""
    nas.run()
    nas.commit("1.5.0")
    (nas.tmp / "docker.log").unlink()
    nas.run()
    log = (nas.tmp / "docker.log").read_text().splitlines()
    assert [l for l in log if l.startswith("rmi")][-1:] == ["rmi bresaola-tracker:0.9.0"]
    assert "rmi bresaola-tracker:1.0.0" not in log and "rmi bresaola-tracker:1.5.0" not in log


def test_only_last_five_database_copies_kept(nas):
    nas.run()
    pre = nas.app / "data" / "pre-update"
    for i in range(8):
        (pre / f"bresaola-2026010{i}-0400.sqlite").write_text("old")
        os.utime(pre / f"bresaola-2026010{i}-0400.sqlite", (1_000_000 + i, 1_000_000 + i))
    nas.commit("1.3.0")
    nas.run()
    assert len(list(pre.glob("bresaola-*.sqlite"))) == 5


def test_setup_writes_public_key(nas, tmp_path):
    env_key = tmp_path / "newkey"
    r = sh("sh", str(nas.app / "scripts" / "nas-update.sh"), "setup",
           env=dict(os.environ, KEY=str(env_key)), check=False)
    if not shutil.which("ssh-keygen"):
        pytest.skip("no ssh-keygen here")
    assert r.returncode == 0, r.stderr
    assert (nas.app / "deploy_key.pub").read_text().startswith("ssh-ed25519 ")
