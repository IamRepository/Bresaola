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
#   4. waits until the app answers; if it doesn't, goes back to the previous version
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

log "updating ${OLD:-zip install} -> $(git_ log -1 --format=%h:%s "$NEW" | cut -c1-70)"
if deploy "$NEW" && healthy; then
    log "OK: $(grep -o '[0-9][0-9.]*' "$APP/bresaola/__init__.py" | head -1) is running"
    # old images (tag = version) take space; keep the one in use
    TAG=$(sed -n 's/^ *image: *bresaola-tracker:\([^ ]*\).*/\1/p' "$APP/compose.yaml")
    docker images bresaola-tracker --format '{{.Tag}}' | grep -vx "$TAG" | while read -r t; do
        docker rmi "bresaola-tracker:$t" >/dev/null 2>&1; done
    exit 0
fi

log "FAILED: new version didn't start; going back"
if [ -n "$OLD" ] && deploy "$OLD" && healthy; then
    log "back on $(git_ log -1 --format=%h "$OLD"); database copy in data/pre-update/bresaola-$STAMP.sqlite"
else
    log "FAILED: previous version didn't start either. Database copy: data/pre-update/bresaola-$STAMP.sqlite"
fi
exit 1
