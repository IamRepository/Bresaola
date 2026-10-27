#!/bin/sh
# Bresaola Tracker: automatic update on the Synology NAS (DSM Task Scheduler, user root).
#
#   sh /volume1/docker/bresaola/scripts/nas-update.sh setup   once: makes the deploy key
#   sh /volume1/docker/bresaola/scripts/nas-update.sh         nightly: update if there is a new version
#
# What a nightly run does:
#   1. asks GitHub for the newest commit on the "stable" branch (read-only deploy key)
#   2. nothing new: stops ("up to date")
#   3. new version: copies the database to data/pre-update/ (keeps the last 5),
#      checks out the new files, rebuilds the image and restarts the container
#   4. checks the new version really runs: web server answers, the container reports the new version
#      and opens the database (this runs any database upgrade); if not, goes back to the previous version
#      (its image is kept) and remembers the bad commit, so it isn't retried every night
# The data folder is never touched by git (it is in .gitignore). Each run writes to update.log.
# Exit code 1 = failed (DSM can e-mail you: task settings -> "only when the script terminates abnormally").

APP=$(cd "$(dirname "$0")/.." && pwd)
BRANCH=${BRANCH:-stable}
PORT=${PORT:-8520}
REPO=${REPO:-git@github.com:IamRepository/Bresaola.git}
KEY=${KEY:-/root/.ssh/bresaola_deploy}
LOG="$APP/update.log"
WAIT=${WAIT:-30}                     # health checks, 10 s apart

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }
git_() { git -c safe.directory="$APP" -C "$APP" "$@"; }   # files belong to the DSM user, the task runs as root
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

compose() {
    if docker compose version >/dev/null 2>&1; then docker compose -p bresaola "$@"
    else docker-compose -p bresaola "$@"; fi
}

healthy() {
    i=0
    while [ "$i" -lt "$WAIT" ]; do
        curl -fs "http://localhost:$PORT/_stcore/health" >/dev/null 2>&1 && return 0
        i=$((i + 1)); sleep 10
    done
    return 1
}

deploy() {                           # check out commit $1, rebuild, restart
    git_ reset -q --hard "$1" && (cd "$APP" && compose up -d --build) >>"$LOG" 2>&1
}

repo_version() { grep -o '[0-9][0-9.]*' "$APP/bresaola/__init__.py" | head -1; }

running_ok() {                       # the new container runs the checked-out version and opens the database
    healthy || return 1
    got=$(docker exec bresaola python -c "import py_compile; py_compile.compile('app.py', cfile='/tmp/app.pyc', doraise=True); \
from bresaola import __version__, db, storage; db.connect(storage.db_path()).close(); print(__version__)" 2>>"$LOG")
    [ "$got" = "$(repo_version)" ] || { log "check: container reports '${got}', expected $(repo_version)"; return 1; }
}

image_tag() { git_ show "$1:compose.yaml" 2>/dev/null | sed -n 's/^ *image: *bresaola-tracker:\([^ ]*\).*/\1/p'; }

# ---- one-time setup: deploy key ---------------------------------------------------------- #
if [ "${1:-}" = "setup" ]; then
    mkdir -p "$(dirname "$KEY")" && chmod 700 "$(dirname "$KEY")"
    [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -C "bresaola-nas" -f "$KEY"
    cp "$KEY.pub" "$APP/deploy_key.pub"
    log "setup: public key written to $APP/deploy_key.pub - add it on GitHub as a read-only deploy key"
    exit 0
fi

cd "$APP" || exit 1
[ -f "$KEY" ] || { log "FAILED: no deploy key, run the setup first"; exit 1; }

# first run: the folder came from a ZIP, make it a git checkout (data/ stays: it's ignored)
if [ ! -d "$APP/.git" ]; then
    git_ init -q && git_ remote add origin "$REPO" || { log "FAILED: git init"; exit 1; }
    log "first run: folder is now a git checkout of $BRANCH"
fi

git_ fetch -q origin "$BRANCH" || { log "FAILED: can't reach GitHub (network, deploy key?)"; exit 1; }
NEW=$(git_ rev-parse "origin/$BRANCH")
OLD=$(git_ rev-parse -q --verify HEAD 2>/dev/null || echo "")
if [ "$OLD" = "$NEW" ]; then
    log "up to date ($(git_ log -1 --format=%h:%s HEAD | cut -c1-70))"
    exit 0
fi
FAILED_FILE="$APP/update.failed"
if [ -f "$FAILED_FILE" ] && [ "$(cat "$FAILED_FILE")" = "$NEW" ]; then
    log "FAILED earlier: $(git_ log -1 --format=%h "$NEW") didn't start, not trying again until stable changes"
    exit 1
fi

# database copy before anything changes (consistent copy via SQLite, from inside the container)
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$APP/data/pre-update"
if ! docker exec bresaola python -c "import sqlite3; s = sqlite3.connect('/data/bresaola.sqlite'); \
d = sqlite3.connect('/data/pre-update/bresaola-$STAMP.sqlite'); s.backup(d); d.close()" >>"$LOG" 2>&1; then
    # container not running: nothing is writing, a plain copy is consistent
    cp "$APP/data/bresaola.sqlite" "$APP/data/pre-update/bresaola-$STAMP.sqlite" \
        || { log "FAILED: database copy, nothing changed"; exit 1; }
fi
ls -1t "$APP"/data/pre-update/bresaola-*.sqlite 2>/dev/null | tail -n +6 | while read -r f; do rm -f "$f"; done
# local edits to compose.yaml would be replaced: keep a copy (Tapo settings belong in .env since v0.4.7)
[ -f "$APP/compose.yaml" ] && cp "$APP/compose.yaml" "$APP/data/pre-update/compose-$STAMP.yaml"
ls -1t "$APP"/data/pre-update/compose-*.yaml 2>/dev/null | tail -n +6 | while read -r f; do rm -f "$f"; done

log "updating ${OLD:-zip install} -> $(git_ log -1 --format=%h:%s "$NEW" | cut -c1-70)"
if deploy "$NEW" && running_ok; then
    rm -f "$FAILED_FILE"
    log "OK: $(repo_version) is running"
    # old images (tag = version) take space; keep this one and the previous one (for a quick way back)
    TAG=$(image_tag "$NEW"); PREV=$( [ -n "$OLD" ] && image_tag "$OLD" )
    docker images bresaola-tracker --format '{{.Tag}}' | grep -vx "$TAG" | grep -vx "${PREV:-$TAG}" |
        while read -r t; do docker rmi "bresaola-tracker:$t" >/dev/null 2>&1; done
    exit 0
fi

echo "$NEW" > "$FAILED_FILE"
log "FAILED: new version didn't start properly; going back (database copy: data/pre-update/bresaola-$STAMP.sqlite)"
if [ -n "$OLD" ]; then
    if deploy "$OLD" && running_ok; then
        log "back on $(git_ log -1 --format=%h "$OLD") ($(repo_version))"
    else
        log "FAILED: previous version didn't start either: restore by hand (docs/NAS.md section 8)"
    fi
else
    # first run (folder came from the ZIP): no previous commit to go back to; forget the checkout so
    # the files stay as they are and the next run starts over
    git_ update-ref -d HEAD 2>/dev/null
    log "FAILED on the first run: see the lines above; Container Manager -> Project -> Build brings the app back"
fi
exit 1
