"""Bresaola Tracker – Streamlit UI.

The batch is shown as a journey: Day 0 (spice and bag) → Cure → Dry → Finish.
Every step is built from the same blocks, in the same order:
    next action → result band → what happened → journal (notes + photos) → setup → Done
Done locks the step and opens the next one.

Run:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import sqlite3
from datetime import date, datetime, time, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from bresaola import __version__, calc, db, report, safety, sensors, storage, tapo_sync
from bresaola.blends import BLENDS
from bresaola.demo import seed_demo

# logo: Material Symbols icon, same style as the owner's other apps (BBQ Chart to Data, BBQ dashboard,
# Brisket Analyzer); takes the text colour, so it follows dark mode. Chosen 28 Oct 2026: option D of 12.
APP_ICON = ":material/scale:"
st.set_page_config(page_title="Bresaola Tracker", page_icon=APP_ICON, layout="wide")

# Light/dark follows Streamlit's own theme (switched with the sidebar toggle, stored in the browser).
DARK = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
PALETTE = {
    #          light      dark
    "RED":      ("#7a2320", "#d0605a"),
    "RED_BG":   ("#f6ece9", "#3a2321"),
    "GREEN":    ("#3e5a44", "#8fc79a"),
    "GREEN_BG": ("#f1f6f1", "#1d2b21"),
    "INK":      ("#2e2a28", "#ece7e4"),
    "MUTED":    ("#7d7672", "#a8a19c"),
    "LINE":     ("#e3dedb", "#3a3634"),
    "SURFACE":  ("#ffffff", "#0e1117"),
    "BORDER":   ("#d9d4d0", "#45403d"),
    "FAINT":    ("#8a8480", "#8f8884"),
    "GREEN_LINE": ("#9db39f", "#3f5e47"),
    "TRACK":    ("#f1efee", "#2b2826"),
    "CHIP_TXT": ("#5f5955", "#c9c2bd"),
    "AMBER":    ("#8a5a00", "#e0b25a"),
    "AMBER_BG": ("#fbf1dc", "#3a2f1a"),
}
(RED, RED_BG, GREEN, GREEN_BG, INK, MUTED, LINE, SURFACE, BORDER, FAINT, GREEN_LINE, TRACK,
 CHIP_TXT, AMBER, AMBER_BG) = (v[DARK] for v in PALETTE.values())

st.markdown(f"""<style>
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{ height: 2.25rem; padding: .5rem 1rem 0; }}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding-top: 0; }}
section[data-testid="stSidebar"] h1 {{ padding-top: 0; }}
.block-container {{ padding-top: 4rem; max-width: 1150px; }}   /* Streamlit top bar is 3.75rem and sits over the page */
.block-container h2 {{ padding-top: 0; }}
/* sidebar popovers (rename/delete, restore): sidebar-sized, compact */
[data-testid="stPopoverBody"] {{ width: 320px !important; min-width: 0 !important; max-width: 92vw !important;
  padding: .8rem 1rem .9rem !important; }}
[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] {{ gap: .55rem; }}
[data-testid="stPopoverBody"] .pop-h {{ font-size: .85rem; font-weight: 700; color: {INK}; margin: 0 0 .15rem; }}
[data-testid="stPopoverBody"] .pop-sep {{ border: 0; border-top: 1px solid {LINE}; margin: .35rem 0; }}
section[data-testid="stSidebar"] .st-key-testmode [data-testid="stAlert"] p {{ font-size: .82rem; }}

/* journey rail */
.st-key-rail [data-testid="stHorizontalBlock"] {{ gap: .5rem; }}
.st-key-rail button {{ height: auto; min-height: 3.6rem; padding: .55rem .8rem; border-radius: 8px;
  justify-content: flex-start; text-align: left; border: 1px solid {BORDER}; background: {SURFACE}; color: {FAINT}; }}
.st-key-rail button p {{ font-weight: 500; font-size: .98rem; text-align: left; line-height: 1.25; }}
.st-key-rail button:hover {{ border-color: {RED}; color: {RED}; }}
.stat {{ margin: .4rem .1rem 0; line-height: 1.35; }}
/* the result band has 5 metrics: at the default size "Estimated finish" was cut off (full audit #6) */
[data-testid="stMetricValue"] {{ font-size: 1.6rem; }}
[data-testid="stMetricValue"] > div {{ overflow: visible; text-overflow: clip; }}
.stat .tag {{ display:inline-block; font-size:.68rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
  padding:.12rem .45rem; border-radius:4px; margin-right:.35rem; vertical-align:1px; }}
.stat .main {{ font-size:.86rem; font-weight:600; color:{INK}; }}
.stat .more {{ display:block; font-size:.8rem; color:{MUTED}; margin-top:.1rem; }}
.stat .more.due {{ color:{RED}; font-weight:600; }}
.stat.done .tag {{ background:{GREEN_BG}; color:{GREEN}; border:1px solid {GREEN_LINE}; }}
.stat.now .tag {{ background:{RED}; color:#fff; }}
.stat.wait .tag {{ background:{TRACK}; color:{FAINT}; }}
.stat.wait .main {{ color:{FAINT}; font-weight:500; }}

/* bands: summary figures at the top of each step */
.band {{ border:1px solid {LINE}; border-radius:10px; padding:1rem 1.25rem .9rem; margin: .25rem 0 1rem; }}
.band .grid {{ display:grid; grid-template-columns:repeat(var(--cols,3),minmax(0,1fr)); column-gap:1.5rem; row-gap:.85rem; }}
.band .lab {{ font-size:.8rem; color:{MUTED}; margin-bottom:.1rem; }}
.band .val {{ font-size:1.4rem; font-weight:600; color:{INK}; line-height:1.2; }}
.band .sub {{ font-size:.8rem; color:{MUTED}; }}
.band .chip {{ font-size:.75rem; padding:.1rem .5rem; border-radius:4px; margin-left:.4rem; vertical-align:middle; font-weight:500; }}
.band .chip.ok {{ background:{GREEN_BG}; color:{GREEN}; }}
.band .chip.over {{ background:{RED_BG}; color:{RED}; }}
.band .chip.warn {{ background:{AMBER_BG}; color:{AMBER}; }}
.band .chip.run {{ background:{TRACK}; color:{CHIP_TXT}; }}
.band .track {{ position:relative; height:8px; background:{TRACK}; border-radius:4px; margin-top:1rem; }}
.band .fill {{ position:absolute; left:0; top:0; bottom:0; background:{RED}; border-radius:4px; }}
.band .mark {{ position:absolute; top:-5px; width:4px; height:18px; background:{SURFACE}; border:1.5px solid {INK};
  border-radius:2px; box-sizing:border-box; }}
.band .ends {{ position:relative; height:1.1rem; font-size:.75rem; color:{MUTED}; margin-top:.3rem; }}
.band .ends span {{ position:absolute; white-space:nowrap; }}
@media (max-width: 640px) {{ .band .grid {{ grid-template-columns:1fr 1fr; }} }}

/* next action */
.next {{ border-left: 4px solid {RED}; background: {RED_BG}; padding: .7rem 1rem; border-radius: 0;
  margin: .25rem 0 1rem; color: {INK}; }}
.next b {{ color: {RED}; }}
.next.done {{ border-left-color: {GREEN}; background: {GREEN_BG}; }}
.next.done b {{ color: {GREEN}; }}

/* block headings inside a step */
.blk {{ font-size: .8rem; letter-spacing: .02em; color: {MUTED}; margin: 1.25rem 0 .35rem;
  border-bottom: 1px solid {LINE}; padding-bottom: .25rem; }}
</style>""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def get_con():
    fresh = not storage.db_path().exists()
    con = db.connect(storage.db_path())
    if fresh and storage.is_test_mode():   # demo only in a brand-new test database
        seed_demo(con)
    return con


def d(s):
    return date.fromisoformat(s) if s else None


def fmt_date(s):
    return d(s).strftime("%d %b %Y") if s else "–"


def act(fn, *a, success: str | None = None, goto: str | None = None, **kw):
    """Run a db action in one transaction, report problems, then rerun.
    goto: open that step afterwards (Done jumps to the next step)."""
    try:
        with con:
            fn(con, *a, **kw)
    except (db.Locked, ValueError) as e:
        st.error(md(e))                   # messages quote names: show them as typed
        return False
    except sqlite3.IntegrityError as e:   # safety net; db functions check first
        st.error(f"Could not save: {e}")
        return False
    if success:
        st.session_state["flash"] = success
    if goto:
        st.session_state[f"step{pid}"] = goto
    st.rerun()


def fresh(key: str, db_value) -> str:
    """Widget key for a control that shows a database value: the value is part of the key. When the
    database changes elsewhere (another tab, the phone, a restore), the control gets a new key, so it is a
    new widget showing the database value; the browser has no old value for it to send back.
    (v0.4.9 only reset the server's copy; the browser kept the old value and saved it back two clicks
    later: full audit 28 Oct 2026, #1.) Use inline: key=fresh(f"w{pid}", p["green_weight_g"])."""
    return f"{key}@{hashlib.sha1(repr(db_value).encode()).hexdigest()[:10]}"


def blk(title: str):
    """Section title. Plain text only: escaped, so a name like "Fridge <old>" shows as typed (audit #12)."""
    st.markdown(f'<div class="blk">{html.escape(title)}</div>', unsafe_allow_html=True)


# characters that format text in the middle of a line (-, #, + and 1. only do so at the start of one,
# and a name never starts a line here)
_MD_SPECIAL = re.compile(r"([\\`*_\[\]|~<>$:])")


def md(s) -> str:
    """User text (project or chamber names) inside Markdown: shown exactly as typed, e.g. My_test_batch
    stays upright and :red[x] stays literal (audit #14)."""
    return _MD_SPECIAL.sub(r"\\\1", str(s).replace("&", "&amp;"))     # &copy; stays "&copy;", not ©


_MD_ALL = re.compile(r"([\\`*_{}\[\]()#+\-.!|~<>$:=])")


def md_text(s) -> str:
    """Multi-line user text (final notes) as typed: every Markdown character escaped, line breaks kept,
    the same as in the PDF (full audit 27 Oct, #6)."""
    out = []
    for line in str(s).replace("&", "&amp;").splitlines():
        body = line.lstrip(" ")              # leading spaces would turn the line into a code block
        out.append("&nbsp;" * (len(line) - len(body)) + _MD_ALL.sub(r"\\\1", body))
    return "  \n".join(out)


def band(cells: list[tuple[str, str, str]], cols: int = 3, extra: str = ""):
    """cells: (label, value html, sub). One summary band."""
    inner = "".join(f'<div><div class="lab">{l}</div><div class="val">{v}</div>'
                    f'<div class="sub">{s or "&nbsp;"}</div></div>' for l, v, s in cells)
    st.markdown(f'<div class="band" style="--cols:{cols}"><div class="grid">{inner}</div>{extra}</div>',
                unsafe_allow_html=True)


con = get_con()
if "photos_shrunk" not in st.session_state:          # one-off tidy-up of photos stored before v0.2.11
    st.session_state["photos_shrunk"] = storage.shrink_existing_photos()

# --------------------------------------------------------------------------- #
# sidebar: project, new project, data
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.title(f"{APP_ICON} Bresaola Tracker")
    st.caption(f"v{__version__}  \nCredit to Eric Pousson from 2 Guys & A Cooler")

    projs = db.projects(con)
    labels = {p["id"]: db.display_name(p) + ("  (closed)" if p["status"] == "closed" else "") for p in projs}
    if projs:
        qp = st.query_params
        if "p" in qp and "proj" not in st.session_state:     # coming back from a theme switch
            try:
                st.session_state["pid_next"] = int(qp["p"])
                if qp.get("s"):
                    st.session_state[f"step{int(qp['p'])}"] = qp["s"]
            except ValueError:
                pass
        qp.clear()
        # The dropdown owns the current project (key "proj"). Other code asks for a switch by
        # setting "pid_next"; it is applied here, before the dropdown is drawn. Never pass an
        # index: a changing index gives the widget a new identity and drops the next pick.
        ids = list(labels)
        if "pid_next" in st.session_state:
            st.session_state["proj"] = st.session_state.pop("pid_next")
        if st.session_state.get("proj") not in ids:
            st.session_state["proj"] = ids[0]
        pid = st.selectbox("Project", ids, key="proj", format_func=labels.get)
        sp = db.project(con, pid)
        with st.popover("Edit or delete", icon=":material/more_horiz:", width="stretch"):
            st.markdown('<p class="pop-h">Rename</p>', unsafe_allow_html=True)
            new_name = st.text_input("New name", value=sp["name"], key=fresh(f"rn{pid}", sp["name"]), label_visibility="collapsed",
                                     help="The date in front comes from the start date and is added automatically.")
            if st.button("Rename", disabled=sp["status"] == "closed" or new_name.strip() in ("", sp["name"]),
                         key=f"rnb{pid}", width="stretch"):
                act(db.rename_project, pid, new_name, success="Renamed")
            st.markdown('<hr class="pop-sep"><p class="pop-h">Start date (day 0)</p>', unsafe_allow_html=True)
            new_start = st.date_input("Day 0 date", value=d(sp["start_date"]), format="DD/MM/YYYY",
                                      max_value=max(db.today(), d(sp["start_date"])),
                                      key=fresh(f"sd{pid}", sp["start_date"]), label_visibility="collapsed",
                                      disabled=sp["status"] == "closed")
            st.caption("The day the meat was trimmed, spiced and bagged. Also the date in the project name.")
            if st.button("Change start date", key=f"sdb{pid}", width="stretch",
                         disabled=sp["status"] == "closed" or new_start == d(sp["start_date"])):
                act(db.set_start_date, pid, new_start, success="Start date changed")
            st.markdown('<hr class="pop-sep"><p class="pop-h">Delete</p>', unsafe_allow_html=True)
            st.caption("Removes the project, its weigh-ins, photos and sensor readings for good. Download a backup first.")
            confirm = st.text_input(f"Type **{md(sp['name'])}** to confirm", key=f"del{pid}")
            if st.button("Delete project permanently", disabled=confirm.strip() != sp["name"],
                         key=f"delb{pid}", width="stretch"):
                with con:
                    db.delete_project(con, pid)
                storage.delete_project_photos(pid)
                st.session_state.pop("pid_next", None)          # falls back to the first project
                st.session_state["flash"] = f"Deleted {md(sp['name'])}"
                st.rerun()
    else:
        pid = None

    with st.expander("New project", expanded=not projs):
        with st.form("new_project", clear_on_submit=True):
            name = st.text_input("Name", placeholder="Valtellina Nov 2026")
            start_d = st.date_input("Start date", value=db.today(), max_value=db.today(), format="DD/MM/YYYY",
                                    help="Day 0: the day the meat is trimmed, spiced and bagged")
            weight = st.number_input("Meat weight [g]", min_value=1.0, value=2000.0, step=1.0, format="%.0f",
                                     help="Raw meat after trimming")
            salt = st.radio("Curing salt", ["With EcoCure #2", "Without curing salt"], index=None,
                            help="No default on purpose: decide for each batch. Without curing salt, protection "
                                 "rests on the salt level and on drying properly.")
            if st.form_submit_button("Create project", type="primary"):
                if not name.strip():
                    st.error("Give the project a name")
                elif salt is None:
                    st.error("Choose whether this batch uses curing salt")
                else:
                    try:
                        with con:
                            new = db.create_project(con, name.strip(), next(iter(BLENDS)),
                                                    salt == "With EcoCure #2", weight, start_d)
                        st.session_state["pid_next"] = new
                        st.session_state[f"step{new}"] = "day0"
                        st.rerun()
                    except ValueError as e:
                        st.error(md(e))

    dark_on = st.toggle("Dark mode", value=DARK, key="dark_mode",
                        help="Saved in this browser. The page reloads to switch.")
    if dark_on != DARK:
        if pid is not None:                                   # keep project and step across the reload
            st.query_params["p"] = str(pid)
            st.query_params["s"] = st.session_state.get(f"step{pid}", "")
        want = "Dark" if dark_on else "Light"
        st.html("<script>localStorage.setItem('stActiveTheme-' + window.location.pathname + '-v2', "
                f"JSON.stringify('{want}')); setTimeout(() => window.location.reload(), 150);</script>",
                unsafe_allow_javascript=True)

    st.divider()
    with st.expander("Data: backup and restore"):
        st.download_button("Download backup", storage.make_backup,   # built only when clicked
                           file_name=f"bresaola-backup-{db.today().isoformat()}.zip",
                           mime="application/zip", width="stretch")
        with st.popover("Restore backup", width="stretch"):
            st.caption("Replaces **all** projects and photos with the contents of the backup.")
            up = st.file_uploader("Backup file (.zip)", type="zip",
                                  key=f"restore{st.session_state.get('restore_n', 0)}")
            if st.button("Replace all data", type="primary", disabled=up is None, width="stretch"):
                con.close()
                try:
                    storage.restore_backup(up.getvalue())
                    st.session_state.pop("pid_next", None)
                    st.session_state["restore_n"] = st.session_state.get("restore_n", 0) + 1   # empty uploader
                    st.session_state["flash"] = "Backup restored. Previous data kept in 'before-restore'."
                except ValueError as e:
                    st.session_state["flash_error"] = f"Nothing was changed. {md(e)}"
                except Exception as e:
                    st.session_state["flash_error"] = f"Restore failed, your data is unchanged: {md(e)}"
                st.rerun()
        # left over from deleted projects (audit #19); a chamber the hub sync feeds is never "unused" (#5)
        if unused := [c for c in db.unused_chambers(con) if not tapo_sync.hub_fed(c)]:
            with st.popover(f"Unused chambers ({len(unused)})", width="stretch"):
                st.caption("Drying chambers no project uses. Deleting one removes its readings too.")
                for c in unused:
                    st.markdown(f"**{md(c['name'])}**: {c['n']} readings")
                    ok_ = st.checkbox("Delete it and its readings", key=f"chdelok{c['id']}")
                    if st.button("Delete chamber", key=f"chdel{c['id']}", disabled=not ok_, width="stretch"):
                        act(db.delete_chamber, c["id"], success=f"Chamber {md(c['name'])} deleted")
    if storage.is_test_mode():
        with st.container(key="testmode"):
            st.warning("**Test mode.** Nothing here is stored permanently. Use *Download backup* "
                       "above to keep anything you enter.", icon="⚠️")

# --------------------------------------------------------------------------- #
# header
# --------------------------------------------------------------------------- #

if msg := st.session_state.pop("flash", None):
    st.toast(msg, icon=":material/check_circle:")
if err := st.session_state.pop("flash_error", None):
    st.toast(err, icon=":material/error:", duration="long")

if pid is None:
    st.info("Create a project in the sidebar to start.")
    st.stop()

p = db.project(con, pid)
closed = p["status"] == "closed"
KIND = db.chamber_kind(con, p)          # 'fridge', 'chamber' or None before drying

# --------------------------------------------------------------------------- #
# journey rail
# --------------------------------------------------------------------------- #

STEPS = ["day0", "cure", "dry", "finish"]
TITLE = {"day0": "Day 0: spice and bag", "cure": "Cure", "dry": "Dry", "finish": "Finish"}
done = {"day0": bool(p["spice_locked_at"]), "cure": bool(p["cure_locked_at"]),
        "dry": bool(p["dry_locked_at"]), "finish": closed}
current = next((s for s in STEPS if not done[s]), "finish")


def reopened(kind: str) -> bool:
    """True if this step (spice, cure, dry) was locked and has since been unlocked for editing."""
    ks = [e["kind"] for e in db.events(con, pid) if e["kind"] in (f"{kind}_locked", f"{kind}_unlocked")]
    return bool(ks) and ks[-1] == f"{kind}_unlocked"


REOPENED = {"day0": reopened("spice"), "cure": reopened("cure")}


WEIGH_EVERY = 7          # days; weigh-ins are roughly weekly, the reminder shows after 6 days


def short(dt) -> str:
    return f"{dt.day} {dt:%b}"


def step_status(s: str) -> tuple[str, str, str, bool]:
    """(state, main line, second line, second line is a warning) for the status under a rail button.
    state: done, now (the step to work on) or wait."""
    state = "done" if done[s] else ("now" if s == current else "wait")
    today = db.today()
    if s in REOPENED and REOPENED[s] and not done[s]:
        return state, "unlocked for editing", "press Done to lock it again", True
    if s == "day0":
        if done[s]:
            return state, short(d(p["start_date"])) + " " + d(p["start_date"]).strftime("%Y"), "spiced and bagged", False
        return state, f"started {short(d(p['start_date']))}", "spice, measure, bag", False
    if s == "cure":
        if done[s] and p["cure_end_actual"]:
            n = (d(p["cure_end_actual"]) - d(p["cure_start"])).days
            return state, f"{n} days in the bag", f"out {short(d(p['cure_end_actual']))}", False
        if state == "now" and p["cure_start"] and p["thickness_cm"]:
            planned = calc.cure_end_date(d(p["cure_start"]), p["thickness_cm"], p["shape"])
            day = (today - d(p["cure_start"])).days
            total = calc.cure_days(p["thickness_cm"], p["shape"])
            return state, f"day {day} of {total}", f"out of the bag {short(planned)}", planned <= today
        return state, "starts after day 0", "", False
    if s == "dry":
        if not p["dry_start"]:
            return state, ("wrap, net, weigh" if state == "now" else "starts after the cure"), "", False
        st_ = db.drying_status(con, pid)
        lost = calc.loss_pct(p["dry_start_gross_g"], st_["latest_gross_g"], p["tare_g"])
        end = d(p["dry_end"]) if p["dry_end"] else today
        main = f"day {(end - d(p['dry_start'])).days} · {lost:.1f} % of {p['target_loss_pct']:g} % lost"
        if done[s]:
            return (state, main, "target reached", False) if st_["progress"] >= 1 else \
                (state, main, "ended below target", True)
        if st_["progress"] >= 1:
            return state, main, "target reached: press Done", False
        last = db.readings(con, pid)[-1][0]
        due = last + timedelta(days=WEIGH_EVERY)
        if due <= today:
            return state, main, "weigh-in due", True
        return state, main, f"next weigh-in by {short(due)}", False
    if closed:
        return state, f"closed {short(d(p['closed_at'][:10]))}", "read-only", False
    if state == "now":
        return state, "tasting notes", "then close the batch", False
    return state, "after drying", f"at {p['target_loss_pct']:g} % weight loss" if p["dry_start"] else "", False


STATE_LABEL = {"done": "Done", "now": "Now", "wait": "Next"}


def status_html(s: str) -> str:
    state, main, more, warn = step_status(s)
    more_html = f'<span class="more{" due" if warn else ""}">{more}</span>' if more else ""
    return (f'<div class="stat {state}"><span class="tag">{STATE_LABEL[state]}</span>'
            f'<span class="main">{main}</span>{more_html}</div>')


step_key = f"step{pid}"
if step_key not in st.session_state:
    st.session_state[step_key] = current
if st.session_state[step_key] not in STEPS:
    st.session_state[step_key] = current
sel = st.session_state[step_key]

# title, facts and the step rail stay at the top while the page scrolls (owner, 28 Oct 2026);
# messages (no curing salt, weigh today ...) come below and scroll with the page
with st.container(key="rail"):
    st.header(md(db.display_name(p)))
    facts = [p["blend"], f"{p['green_weight_g']:.0f} g raw meat after trimming",
             "EcoCure #2" if p["ecocure"] else "no EcoCure", f"started {d(p['start_date']):%d %b %Y}"]
    if closed:
        facts.append(f"closed {d(p['closed_at'][:10]):%d %b %Y}")
    st.caption(",  ".join(facts))
    cols = st.columns(4)
    css = []
    for i, s in enumerate(STEPS):
        icon = ":material/check_circle:" if done[s] else (
            ":material/radio_button_checked:" if s == current else ":material/radio_button_unchecked:")
        with cols[i]:
            if st.button(f"{icon} {i + 1}. {TITLE[s]}", key=f"rail_{s}", width="stretch"):
                st.session_state[step_key] = s
                st.rerun()
            st.markdown(status_html(s), unsafe_allow_html=True)
        k = f".st-key-rail_{s} button"
        # state colour (done = green, current = red outline) is kept when viewing;
        # the step you are looking at gets a heavy underline-shadow and bold text
        if done[s]:
            css.append(f"{k}, {k}:hover, {k}:focus {{ background:{GREEN_BG} !important; "
                       f"border-color:{GREEN_LINE} !important; color:{GREEN} !important; }}")
        elif s == current:
            css.append(f"{k}, {k}:hover, {k}:focus {{ border:2px solid {RED} !important; "
                       f"color:{RED} !important; background:{SURFACE} !important; }}")
        if s == sel:
            col = GREEN if done[s] else RED
            css.append(f"{k} {{ box-shadow: inset 0 -4px 0 {col} !important; }} {k} p {{ font-weight:700; }}")
    # Streamlit wraps the container in a layout wrapper of the same height: that wrapper must stick.
    # On narrow screens the 4 steps stack, so a fixed top would fill the screen: it scrolls there.
    css.append(f'div[data-testid="stLayoutWrapper"]:has(> .st-key-rail) {{ position: sticky; top: 3.75rem; '
               f'z-index: 100; background: {SURFACE}; padding: .25rem 0 .6rem; border-bottom: 1px solid {LINE}; }}'
               f'@media (max-width: 700px) {{ div[data-testid="stLayoutWrapper"]:has(> .st-key-rail) '
               f'{{ position: static; border-bottom: 0; }} '
               # the steps stack there: Streamlit's -16px under each status pulled the next button over it
               f'.st-key-rail [data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }} }}'   # full audit #4
               f'header[data-testid="stHeader"] {{ background: {SURFACE}; }}')   # no content showing above it
    # compact (owner chose variant B, 28 Oct 2026): smaller title and buttons, one status line per step;
    # the fixed part is 163 px instead of 234 px. The previous design is on branch design/before-sticky-top.
    css.append(".st-key-rail h2 { font-size: 1.45rem !important; padding: .1rem 0 0 !important; margin: 0 !important; }"
               ".st-key-rail [data-testid='stCaptionContainer'] { margin-top: 0; }"
               ".st-key-rail [data-testid='stHeadingWithActionElements'] { margin-bottom: 0 !important; }"
               ".st-key-rail button { min-height: 2.2rem !important; padding: .2rem .5rem !important; }"
               ".st-key-rail .stat .more:not(.due) { display: none; }")   # warnings (red) stay visible
    st.markdown("<style>" + "\n".join(css) + "</style>", unsafe_allow_html=True)

if not p["ecocure"]:
    dry_rows = (db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"])
                if p["chamber_id"] and p["dry_start"] else [])
    level, text = safety.no_cure_message(KIND, dry_rows)
    (st.warning if level == "warning" else st.info)(text, icon=":material/warning:" if level == "warning"
                                                      else ":material/info:")


def next_action() -> tuple[str | None, bool]:
    """(sentence, is_all_done) describing what to do now for the whole batch.
    sentence is None when there is nothing to do today (drying, weighed within the week)."""
    if closed:
        return "This batch is closed. Everything is read-only.", True
    if current in REOPENED and REOPENED[current]:
        name = TITLE[current].split(":")[0]
        return (f"<b>{name} is unlocked for editing.</b> Make your corrections, then press <b>Done</b> "
                "to lock it again.", False)
    if current == "day0":
        return ("<b>Day 0:</b> weigh the trimmed meat, choose the blend, weigh out the spices, measure the "
                "piece and seal it in the bag. Then press <b>Done</b>.", False)
    if current == "cure" and not (p["cure_start"] and p["thickness_cm"]):
        return ("<b>Day 0 is locked, but the bag date and thickness are missing.</b> Unlock day 0, "
                "add them under <i>3 · Measure the piece</i> and press <b>Done</b> again.", False)
    if current == "cure":
        planned = calc.cure_end_date(d(p["cure_start"]), p["thickness_cm"], p["shape"])
        left = (planned - db.today()).days
        if left > 0:
            return (f"<b>Curing:</b> flip and massage the bag daily. {left} days to go, "
                    f"planned out of the bag on {planned:%d %b}.", False)
        return ("<b>Unbag:</b> the planned cure time is reached. Enter the date it came out of the bag "
                "and press <b>Done</b>.", False)
    if current == "dry":
        if not p["dry_start"]:
            return "<b>Wrap, net and weigh</b> the piece, then start drying.", False
        last = db.readings(con, pid)[-1][0]
        ago = (db.today() - last).days
        s_ = db.drying_status(con, pid)
        if s_["progress"] >= 1:
            return "<b>Target weight reached.</b> Enter the end date and press <b>Done</b>.", False
        if ago < WEIGH_EVERY:
            return None, False
        return (f"<b>Weigh today.</b> Last weigh-in {ago} day{'s' if ago != 1 else ''} ago "
                f"({s_['latest_gross_g']:.0f} g, {min(s_['progress'], 1)*100:.0f} % of the way).", False)
    return "<b>Finish:</b> write your tasting notes and close the batch.", False


txt, all_done = next_action()
if txt:
    go_btn = sel != current and not closed
    nc1, nc2 = st.columns([5, 1], vertical_alignment="center") if go_btn else (st.container(), None)
    nc1.markdown(f'<div class="next{" done" if all_done else ""}">{txt}</div>', unsafe_allow_html=True)
    if go_btn and nc2.button(f"Go to {TITLE[current].split(':')[0]}", key="go_current", width="stretch"):
        st.session_state[step_key] = current
        st.rerun()


# --------------------------------------------------------------------------- #
# shared blocks
# --------------------------------------------------------------------------- #

STAGE_NAME = {"spice": "Day 0", "cure": "Cure", "dry": "Dry", "equalise": "Equalise", None: "Other"}


def show_photos(rows, cols_n=4):
    cols = st.columns(cols_n)
    for i, r in enumerate(rows):
        f = storage.photo_file(r["path"])
        with cols[i % cols_n]:
            try:
                st.image(str(f), width="stretch")
            except Exception:  # missing or unreadable file must not break the page
                st.warning("Can't show this photo" if f.exists() else "Photo file missing")
            st.caption(f"{fmt_date(r['taken_at'][:10])}" + (f", {md(r['caption'])}" if r["caption"] else ""))
            if not closed:                       # closed projects keep their photos as they are
                photo_menu(r)


def photo_menu(r):
    """Edit the caption or delete one photo (open projects only)."""
    k = r["id"]
    with st.popover("Edit photo", icon=":material/more_horiz:", type="tertiary", key=f"phm{k}"):
        cap = st.text_input("Caption", value=r["caption"] or "", key=fresh(f"phc{k}", r["caption"] or ""),
                            placeholder="optional")
        if st.button("Save caption", key=f"phs{k}", width="stretch",
                     disabled=(cap.strip() or None) == (r["caption"] or None)):
            act(db.set_photo_caption, k, cap, success="Caption saved")
        st.markdown('<hr class="pop-sep">', unsafe_allow_html=True)
        sure = st.checkbox("Delete this photo for good", key=f"phx{k}")
        if st.button("Delete photo", key=f"phd{k}", width="stretch", disabled=not sure):
            try:
                with con:
                    path = db.delete_photo(con, k)
            except (db.Locked, ValueError) as e:
                st.error(md(e))
                return
            gone = storage.delete_photo_file(path)   # after the commit: no photo row without its file
            st.session_state["flash"] = ("Photo deleted" if gone or not storage.photo_file(path).exists() else
                                         f"Photo removed from the app; its file could not be deleted ({path})")
            st.rerun()


def journal(stage: str, note_value: str | None, save_note, placeholder: str) -> str:
    """Notes and photos for one step. Always open unless the project is closed.
    Returns the note text currently on screen (callers may save it with Done)."""
    blk("Journal: notes and photos")
    note = st.text_area("Notes", value=note_value or "", height=100, key=fresh(f"note_{stage}{pid}", note_value or ""),
                        disabled=closed, placeholder=placeholder)
    if not closed and (note.strip() or None) != (note_value or None):
        if st.button("Save notes", key=f"savenote_{stage}{pid}"):
            act(save_note, pid, note.strip(), success="Notes saved")
    rows = db.photos(con, pid, stage)
    if rows:
        show_photos(rows)
    if not closed:
        with st.expander("Add photos", expanded=False):
            with st.form(f"photo{pid}{stage}", clear_on_submit=True, border=False):
                c1, c2, c3 = st.columns([3, 1, 2], vertical_alignment="bottom")
                files = c1.file_uploader("Photos", type=storage.UPLOAD_TYPES,
                                         accept_multiple_files=True, label_visibility="collapsed")
                taken = c2.date_input("Taken on", value=db.today(), format="DD/MM/YYYY")
                cap = c3.text_input("Caption", placeholder="optional")
                if st.form_submit_button("Upload") and files:
                    added, failed = 0, []
                    with con:
                        for f in files:
                            try:
                                rel = storage.save_photo(pid, f.name, f.getvalue())   # shrunk to 1600 px
                            except ValueError:
                                failed.append(f.name)
                                continue
                            db.add_photo(con, pid, rel, taken, cap or None, stage=stage)
                            added += 1
                    if failed:
                        st.session_state["flash_error"] = "Not a readable photo: " + ", ".join(failed)
                    if added:
                        st.session_state["flash"] = f"{added} photo(s) added"
                    st.rerun()
    return note


def unlock_panel(step: str, locked_at: str, unlock_fn, label: str):
    try:
        when = datetime.fromisoformat(locked_at).strftime("%-d %b %Y, %H:%M")
    except ValueError:
        when = locked_at[:16].replace("T", " ")
    st.caption(f"{label} locked on {when}. "
               "Notes and photos can still be added.")
    blocker = {"spice": ("cure_locked_at", "the cure"), "cure": ("dry_locked_at", "drying")}.get(step)
    if blocker and p[blocker[0]]:
        st.caption(f"To edit {label.lower()}, unlock {blocker[1]} first: the steps after it depend on it.")
        return
    with st.expander(f"Unlock {label.lower()} to edit"):
        reason = st.text_input("Reason (saved in history)", key=f"unl{step}{pid}")
        if st.button(f"Unlock {label.lower()}", disabled=not reason.strip(), key=f"unlb{step}{pid}"):
            act(unlock_fn, pid, reason.strip(), success=f"{label} unlocked", goto=
                {"spice": "day0", "cure": "cure", "dry": "dry"}[step])


# --------------------------------------------------------------------------- #
# step 1: Day 0 – spice and bag
# --------------------------------------------------------------------------- #

def step_day0():
    locked = bool(p["spice_locked_at"]) or closed
    piece_locked = locked or bool(p["cure_locked_at"])
    lines = db.ingredient_lines(con, pid)
    pending = False                       # True while the "reset my amounts?" question is open

    blk("1 · The meat and the recipe")
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
        blend_opts = list(BLENDS) if p["blend"] in BLENDS else [p["blend"]] + list(BLENDS)
        new_b = c1.selectbox("Blend", blend_opts, index=blend_opts.index(p["blend"]), key=fresh(f"b{pid}", p["blend"]),
                             disabled=locked, format_func=lambda b: b if b in BLENDS else f"{b} (saved recipe)")
        new_w = c2.number_input("Meat weight after trimming [g]", min_value=1.0, step=1.0, format="%.0f",
                                value=float(p["green_weight_g"]), key=fresh(f"w{pid}", float(p["green_weight_g"])),
                                disabled=locked)
        new_e = c3.toggle("EcoCure #2", value=bool(p["ecocure"]), key=fresh(f"e{pid}", bool(p["ecocure"])), disabled=locked,
                          help="Chosen when you created the project. Change it here until day 0 is locked; "
                               "switching it off asks first. EcoCure #2 adds 1 % curing salt and lowers the "
                               "kosher salt by half its weight, so total salt stays at 3 %.")
        if not locked:
            changed = (new_b != p["blend"] or new_w != p["green_weight_g"] or new_e != bool(p["ecocure"]))

            def apply_recipe_change(con_, pid_):
                if new_b != p["blend"]:
                    db.change_blend(con_, pid_, new_b)
                db.update_spice_inputs(con_, pid_, green_weight_g=new_w, ecocure=new_e)

            edited = db.actuals_edited(con, pid)
            if changed and p["ecocure"] and not new_e:
                # switching curing salt off is a food-safety choice: confirm it (owner, 28 Oct 2026)
                pending = True
                st.warning("**Switch off EcoCure #2?** Without curing salt (nitrite) this batch's protection rests "
                           f"on the 3 % salt and on drying in a fridge kept below {safety.TEMP_MAX['fridge']:g} °C."
                           + (" Your actual amounts and notes are also **replaced by the new plan**." if edited else ""))
                c1, c2, _ = st.columns([1.6, 1, 2])
                if c1.button("Yes, without curing salt", type="primary", key=f"nocure_ok{pid}", width="stretch"):
                    act(apply_recipe_change, pid, success="EcoCure #2 switched off; plan recalculated")
                if c2.button("Keep EcoCure #2", key=f"nocure_no{pid}", width="stretch"):
                    for k_ in (fresh(f"b{pid}", p["blend"]), fresh(f"w{pid}", float(p["green_weight_g"])),
                               fresh(f"e{pid}", bool(p["ecocure"]))):
                        st.session_state.pop(k_, None)
                    st.rerun()
            elif changed and not edited:
                act(apply_recipe_change, pid, success="Plan recalculated")
            elif changed:
                pending = True
                st.warning("You have entered actual amounts or notes. Changing blend, weight or EcoCure "
                           "recalculates the plan and **replaces them with the new plan**.")
                c1, c2, _ = st.columns([1.6, 1, 2])
                if c1.button("Recalculate and reset", type="primary", key=f"rc_ok{pid}", width="stretch"):
                    act(apply_recipe_change, pid, success="Plan recalculated; actual amounts reset")
                if c2.button("Keep my amounts", key=f"rc_no{pid}", width="stretch"):
                    for k_ in (fresh(f"b{pid}", p["blend"]), fresh(f"w{pid}", float(p["green_weight_g"])),
                               fresh(f"e{pid}", bool(p["ecocure"]))):
                        st.session_state.pop(k_, None)
                    st.rerun()

    # --- spices ----------------------------------------------------------- #
    blk("2 · Weigh out the spices")

    def table(rows, unit_rate, unit_qty, key):
        df = pd.DataFrame([{
            "Ingredient": l["name"],
            f"Rate [{unit_rate}]": f"{l['rate']*100:.3g}" if l["unit"] == "pct" else f"{l['rate']:g}",
            f"Plan [{unit_qty}]": float(l["planned"]),
            f"Actual [{unit_qty}]": None if l["actual"] is None else float(l["actual"]),
            "Note": l["note"] or "",
        } for l in rows])
        fmt = "%.1f" if unit_qty == "g" else "%d"
        return st.data_editor(
            df, hide_index=True, width="stretch", disabled=locked, key=key,
            column_config={
                "Ingredient": st.column_config.TextColumn(disabled=True, width="medium"),
                f"Rate [{unit_rate}]": st.column_config.TextColumn(disabled=True, width="small"),
                f"Plan [{unit_qty}]": st.column_config.NumberColumn(disabled=True, format=fmt, width="small"),
                f"Actual [{unit_qty}]": st.column_config.NumberColumn(format=fmt, min_value=0.0, width="small"),
                "Note": st.column_config.TextColumn(width="large"),
            })

    weighed = [l for l in lines if l["unit"] == "pct"]
    counted = [l for l in lines if l["unit"] == "per_kg"]
    ver = p["spice_locked_at"] or ""
    # the key changes whenever the plan is rewritten, so unsaved edits never land on other rows
    # ... and whenever saved amounts or notes change (another tab, a restore): a stale table must never
    # write its old values back on Save or Done (full audit 27 Oct, #1)
    saved = hash(tuple((l["actual"], l["note"]) for l in lines))
    plan_id = f"{pid}{ver}{p['blend']}{p['ecocure']}{p['green_weight_g']}{saved}"
    ed_w = table(weighed, "%", "g", f"sw{plan_id}")
    ed_c = table(counted, "pcs / kg", "pcs", f"sc{plan_id}") if counted else None

    acts = []
    for rows, ed, u in ((weighed, ed_w, "g"), (counted, ed_c, "pcs")):
        if ed is None:
            continue
        for l, (_, r) in zip(rows, ed.iterrows()):
            a = r[f"Actual [{u}]"]
            n_ = r["Note"]
            n_ = None if n_ is None or (isinstance(n_, float) and pd.isna(n_)) else (str(n_).strip() or None)
            acts.append((l, None if pd.isna(a) else float(a), n_))
    weight = p["green_weight_g"]
    plan_g = sum(l["planned"] for l in weighed)
    act_g = sum(a or 0 for l, a, _ in acts if l["unit"] == "pct")
    plan_mix = calc.mix_summary([(l["name"], l["unit"], l["planned"]) for l in lines], weight)
    act_mix = calc.mix_summary([(l["name"], l["unit"], a) for l, a, _ in acts], weight)

    with st.container(border=True):
        cols = st.columns(6 if p["ecocure"] else 5)
        cols[0].metric("Total planned [g]", f"{plan_g:.1f}")
        cols[1].metric("Total actual [g]", f"{act_g:.1f}", delta=f"{act_g - plan_g:+.1f} g", delta_color="off")
        cols[2].metric("Salt [% of meat]", f"{act_mix.salt_pct:.1f}",
                       delta=f"{act_mix.salt_pct - plan_mix.salt_pct:+.1f} vs plan", delta_color="off",
                       help="Kosher salt plus the salt inside EcoCure #2 (half its weight), "
                            "divided by the meat weight. Plan is 3.0.")
        i = 3
        if p["ecocure"]:
            cols[i].metric("EcoCure [% of meat]", f"{act_mix.ecocure_pct:.1f}",
                           delta=f"{act_mix.ecocure_pct - plan_mix.ecocure_pct:+.1f} vs plan", delta_color="off")
            i += 1
        cols[i].metric("Sugar [% of meat]", f"{act_mix.sugar_pct:.1f}")
        cols[i + 1].metric("Spices [% of meat]", f"{act_mix.seasoning_pct:.1f}",
                           help="All weighed ingredients except salt, EcoCure and sugar.")
        off = calc.off_plan([(l["name"], l["planned"], a) for l, a, _ in acts])
        if off:
            st.caption("More than 10 % off plan: " + ", ".join(f"{n} ({dv*100:+.0f} %)" for n, dv in off))

    # --- the piece and the bag -------------------------------------------- #
    blk("3 · Measure the piece and seal the bag")
    k = f"cure{pid}_"
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1.3], vertical_alignment="bottom")
        shape = c1.segmented_control("Shape", ["tubular", "flat"], default=p["shape"] or "tubular",
                                     key=k + "shape", disabled=piece_locked,
                                     help="Tubular: eye of round, tenderloin. Flat: brisket.") or "tubular"
        thick = c2.number_input("Thickness [cm]", min_value=0.5, step=0.5, format="%.1f",
                                value=float(p["thickness_cm"] or 8.0), key=k + "thick", disabled=piece_locked,
                                help="Narrowest dimension across the thickest part. This sets the cure time.")
        length = c3.number_input("Length [cm]", min_value=0.0, step=0.5, format="%.1f",
                                 value=float(p["length_cm"]) if p["length_cm"] else None,
                                 placeholder="optional", key=k + "len", disabled=piece_locked,
                                 help="Used only to check the measurements against the weight.")
        bag = c4.date_input("Into the bag", value=d(p["cure_start"]) or d(p["start_date"]), format="DD/MM/YYYY",
                            key=k + "start", disabled=piece_locked)
        est = st.checkbox("Thickness is an estimate", value=bool(p["thickness_estimated"]),
                          key=k + "est", disabled=piece_locked)
        days = calc.cure_days(thick, shape)
        st.caption(f"Cure time: **{days} days** (calculator {calc.cure_days_minimum(thick, shape):.1f} days + 20 %), "
                   f"out of the bag on **{calc.cure_end_date(bag, thick, shape):%d %b %Y}**.")
        if shape == "tubular" and length:
            implied_g = 1.05 * 3.1416 * (thick / 2) ** 2 * length
            if not 0.6 < implied_g / p["green_weight_g"] < 1.6:
                st.warning(f"A {thick:g} × {length:g} cm piece would weigh about {implied_g:.0f} g, "
                           f"but this one weighs {p['green_weight_g']:.0f} g. Check the measurements.")

    note = journal("spice", p["spice_note"], db.set_spice_note,
                   "e.g. used fresh rosemary, ground the pepper myself, mixed by hand")

    # --- done ----------------------------------------------------------------- #
    def save_all(con_, pid_):
        for l, a, n in acts:
            db.set_actual(con_, pid_, l["position"], a, n)
        db.set_spice_note(con_, pid_, note.strip())
        if not p["cure_locked_at"]:
            db.set_cure(con_, pid_, shape=shape, thickness_cm=thick, length_cm=length or None,
                        thickness_estimated=est, start=bag, end_actual=d(p["cure_end_actual"]),
                        note=p["cure_note"])

    def save_and_lock(con_, pid_):
        save_all(con_, pid_)
        db.lock_spice(con_, pid_)

    blk("Done")
    if closed:
        return
    if not p["spice_locked_at"]:
        b1, b2, _ = st.columns([1.2, 2.2, 3])
        if b1.button("Save", key=f"save_day0{pid}", width="stretch", disabled=pending):
            act(save_all, pid, success="Saved")
        if b2.button("Done: lock day 0 and start curing", type="primary", key=f"done_day0{pid}",
                     width="stretch", disabled=pending):
            act(save_and_lock, pid, success="Day 0 locked. Curing has started.", goto="cure")
        if pending:
            st.caption("Answer the question under *1 · The meat and the recipe* first.")
    else:
        unlock_panel("spice", p["spice_locked_at"], db.unlock_spice, "Day 0")


# --------------------------------------------------------------------------- #
# step 2: cure
# --------------------------------------------------------------------------- #

def step_cure():
    if not p["spice_locked_at"] and not p["cure_locked_at"]:
        st.info("Lock day 0 first: press **Done** on day 0. The cure starts from the bag date entered there.")
        return
    if not p["cure_start"] or not p["thickness_cm"]:
        st.info("The bag date and thickness are missing. Unlock day 0, add them under "
                "*3 · Measure the piece* and press **Done** again." if p["spice_locked_at"] else
                "Finish day 0 first: the cure time comes from the piece's thickness and the bag date.")
        return
    c_locked = bool(p["cure_locked_at"]) or closed
    k = f"cure{pid}_"
    start, thick, shape = d(p["cure_start"]), p["thickness_cm"], p["shape"]
    end_act = st.session_state.get(k + "end", d(p["cure_end_actual"]))
    days = calc.cure_days(thick, shape)
    mins = calc.cure_days_minimum(thick, shape)
    planned = calc.cure_end_date(start, thick, shape)

    today = db.today()
    run_to = end_act or today
    actual_days = (run_to - start).days if start <= run_to else 0
    diff = actual_days - days
    length = safety.cure_length(actual_days, mins, days) if end_act else None
    if end_act:
        act_val, act_sub = f"{end_act:%d %b %Y}", "out of the bag"
        # longer is safe with equilibrium curing (green); short of the +20 % margin amber; below minimum red
        cls = {"ok": "ok", "short": "warn", "below_min": "over"}[length]
        label = "as planned" if diff == 0 else (f"{diff:+d} vs plan" if length != "below_min" else "below minimum")
        chip = f'<span class="chip {cls}">{label}</span>'

    else:
        left = (planned - today).days
        act_val, act_sub = "Still curing", (f"{left} days to go" if left > 0 else
                                             "planned end reached" if left == 0 else f"{-left} days past plan")
        chip = '<span class="chip run">so far</span>'
    span = max((max(planned, run_to) - start).days, 1)
    fill = 100 * min(actual_days, span) / span
    mark = 100 * days / span
    timeline = (f'<div class="track"><div class="fill" style="width:{fill:.1f}%"></div>'
                f'<div class="mark" style="left:calc({mark:.1f}% - 1px)" title="Planned end"></div></div>'
                f'<div class="ends"><span style="left:0">{start:%d %b}</span>'
                f'<span style="left:{mark:.1f}%; transform:translateX({"-100%" if mark > 80 else "-50%"})">'
                f'▲ planned end {planned:%d %b}'
                # near the right end the two labels would overlap: the bar's end goes into the same label
                + (f' · {"out" if end_act else "today"} {run_to:%d %b}' if mark > 80 and run_to > planned else '')
                + '</span>'
                + ('' if mark > 80 else f'<span style="right:0">{max(planned, run_to):%d %b}</span>') + '</div>')
    st.markdown('<span class="cureband"></span>', unsafe_allow_html=True)   # marker for tests
    band([("Cure started", f"{start:%d %b %Y}", "into the bag"),
          ("Planned end", f"{planned:%d %b %Y}", "start + planned days"),
          ("Actual end", act_val, act_sub),
          ("Calculator minimum", f"{mins:.1f} days", "before the 20 % margin"),
          ("Planned days", f"{days} days", "minimum + 20 %, rounded up"),
          ("Actual days", f"{actual_days} days{chip}",
           {"ok": "longer is safe with equilibrium curing" if diff > 0 else "",
            "short": "past the calculator minimum, but not the +20 % margin",
            "below_min": "shorter than the calculator minimum: salt may not have reached the centre",
            None: ""}[length])], extra=timeline)
    if length == "below_min":
        st.error(f"This cure ({actual_days} days) is shorter than the calculator minimum ({mins:.1f} days). "
                 "The salt may not have reached the centre of the piece.")
    elif length == "short":
        st.warning(f"This cure ({actual_days} days) is past the calculator minimum ({mins:.1f} days) but "
                   f"short of the planned {days} days, which include a 20 % safety margin.")

    blk("Unbag")
    with st.container(border=True):
        c1, c3, c2 = st.columns([1, 1, 2], vertical_alignment="bottom")
        c1.date_input("Taken out of the bag", value=d(p["cure_end_actual"]), format="DD/MM/YYYY",
                      key=k + "end", disabled=c_locked, help="Leave empty while the meat is still curing")
        fridge = c3.number_input("Cure fridge [°C]", value=p["cure_fridge_c"], min_value=-5.0, max_value=30.0,
                                 step=0.5, format="%.1f", placeholder="optional", key=k + "fridge",
                                 disabled=c_locked, help="Temperature of the fridge the bag cures in. "
                                 "The cure time assumes 1-3 °C.")
        c2.caption(f"Piece: {shape}, {thick:g} cm{' (estimate)' if p['thickness_estimated'] else ''}. "
                   "Change it on day 0.")
        if end_act and end_act < start:
            st.error("'Taken out of the bag' is before 'Into the bag'. Check the date.")
        if w_ := safety.cure_fridge_warning(fridge):
            st.warning(w_)

    note = journal("cure", p["cure_note"], db.set_cure_note,
                   "Method and exceptions, e.g. flipped daily; missed a flip on day 12")

    def save_cure(con_, pid_):
        db.set_cure(con_, pid_, shape=shape, thickness_cm=thick, length_cm=p["length_cm"],
                    thickness_estimated=bool(p["thickness_estimated"]), start=start, end_actual=end_act,
                    method=None, note=note.strip() or None)
        db.set_cure_fridge(con_, pid_, fridge)

    confirm_short = False

    def save_and_lock(con_, pid_):
        save_cure(con_, pid_)
        db.lock_cure(con_, pid_, confirm_short=confirm_short)

    blk("Done")
    if not closed:
        if not p["cure_locked_at"]:
            if length == "below_min":
                confirm_short = st.checkbox("I know this cure is shorter than the calculator minimum and want to "
                                            "lock it anyway (recorded in the history and the PDF)",
                                            key=f"short_ok{pid}")
            b1, b2, _ = st.columns([1.2, 2.2, 3])
            unchanged = ((end_act.isoformat() if end_act else None) == p["cure_end_actual"]
                         and fridge == p["cure_fridge_c"])
            if b1.button("Save", key=f"save_cure{pid}", width="stretch", disabled=unchanged):
                act(save_cure, pid, success="Cure saved")
            if b2.button("Done: lock cure and start drying", type="primary", key=f"done_cure{pid}",
                         width="stretch", disabled=not end_act or (length == "below_min" and not confirm_short),
                         help=None if end_act else "Enter the date it came out of the bag first"):
                act(save_and_lock, pid, success="Cure locked. Next: wrap, net and weigh.", goto="dry")
        else:
            unlock_panel("cure", p["cure_locked_at"], db.unlock_cure, "Cure")
    st.caption("Cure time uses the genuineideas.com equilibrium calculator: 1.25 × (thickness in inches)² "
               "days for flat, half for tubular, +20 % to reach the centre. Assumes a fridge at 1–3 °C.")


# --------------------------------------------------------------------------- #
# step 3: dry
# --------------------------------------------------------------------------- #

def save_weigh_in(r: dict, confirmed: bool = False) -> None:
    """Weigh-in + optional chamber reading, in one transaction. Photos go through the journal
    ("Add photos") since v0.4.16: one place for photos (owner, 28 Oct 2026)."""
    try:
        with con:
            db.add_reading(con, pid, r["day"], r["weight"], r["note"], confirmed=confirmed)
            if (r["temp"] is not None or r["rh"] is not None) and p["chamber_id"]:
                db.add_chamber_reading(con, p["chamber_id"], sensors.weigh_in_time(r["day"]).isoformat(),
                                       r["temp"], r["rh"])          # weigh-ins count as 12:00
    except (db.Locked, ValueError) as e:
        st.error(md(e))
        return
    st.session_state["flash"] = f"Saved {r['weight']:.0f} g on {r['day']:%d %b}"
    st.rerun()


def step_dry_start():
    if not p["cure_locked_at"] and not closed:
        st.info("Lock the cure first. Drying then starts on the day the meat came out of the bag.")
    blk("Wrap, net and weigh")
    # type outside the form: it is a required choice and must react before "Start drying" (audit 26 Oct, #1).
    # Each batch has its own sensor and readings (v0.4.17), so there is no chamber to pick.
    c4, c5 = st.columns([1.4, 1])
    new_kind = c4.radio("Drying in", list(safety.KINDS), format_func=safety.KINDS.get,
                        horizontal=True, index=None, key=f"drynewkind{pid}",
                        help="Fridge: about 0-4 °C. Curing chamber: about 10-15 °C. Sets the temperature rules.")
    tapo = c5.text_input("Tapo sensor name (optional)", key=f"drytapo{pid}", placeholder="as in the Tapo app",
                         help="The name of this batch's sensor in the Tapo app. Only needed for the hub sync; "
                              "imports from the Tapo app work without it.")
    with st.form(f"drystart{pid}"):
        c1, c2, c3 = st.columns(3)
        ds = c1.date_input("Drying start", value=d(p["cure_end_actual"]) or db.today(), format="DD/MM/YYYY",
                           help="Defaults to the day the meat came out of the bag")
        sg = c2.number_input("Start weight incl. wrap + net [g]", min_value=1.0, value=None,
                             step=1.0, format="%.0f", placeholder="weigh it now",
                             help="Weigh the piece after wrapping and netting, before hanging it")
        tp = c3.number_input("Target loss [%]", min_value=safety.TARGET_MIN, max_value=safety.TARGET_MAX,
                             value=35.0, step=1.0,
                             help=f"Allowed {safety.TARGET_MIN:g}-{safety.TARGET_MAX:g} %, usual "
                                  f"{safety.TARGET_USUAL[0]:g}-{safety.TARGET_USUAL[1]:g} %. " "Measured on the meat at the start of drying: start weight minus packaging.")
        with st.expander("Packaging weight (optional)"):
            tare = st.number_input("Packaging: wrap + net [g]", min_value=0.0, value=0.0, step=1.0, format="%.0f")
            tare_est = st.checkbox("Packaging weight is an estimate", value=True)
        if st.form_submit_button("Start drying", type="primary", disabled=closed or not p["cure_locked_at"]):
            if sg is None:
                st.error("Enter the start weight: weigh the piece with wrap and net.")
                return
            if not new_kind:
                st.error("Choose where it dries: fridge or curing chamber. It sets the temperature rules.")
                return

            def start_drying(con_, pid_):          # one transaction: no stray sensor table if drying fails
                ch = db.project_chamber(con_, pid_, kind=new_kind, tapo_name=tapo)
                db.set_drying(con_, pid_, start=ds, start_gross_g=sg, chamber_id=ch, tare_g=tare,
                              tare_estimated=tare_est, target_loss_pct=tp)
            act(start_drying, pid, success="Drying started")


def climate_cell(m, i: int) -> str:
    """Day average for the table; * = partial day (sensor reported for less than half the day);
    ⚠ = outside the safe drying range (see bresaola/safety.py)."""
    if not m or m[i] is None:
        return "–"
    flag = " ⚠" if safety.out_of_range("t" if i == 0 else "h", m[i], KIND or "fridge") else ""
    return (f"{m[i]:.1f}" if i == 0 else f"{m[i]:.0f}") + ("*" if m[3] else "") + flag


def period_cell(m, i: int) -> str:
    return climate_cell(m, i)            # same layout: (temp, rh, readings, partial, ...)


def weigh_in_periods() -> dict:
    """{weigh-in day: (avg temp, avg rh, readings, partial, coverage) since the previous weigh-in}."""
    if not p["chamber_id"]:
        return {}
    cr = db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"])
    return sensors.period_averages([d(r["day"]) for r in db.reading_rows(con, pid)], cr)


def weigh_in_climate() -> dict:
    """{weigh-in day: (avg temp, avg rh, readings, partial) or None} from the drying chamber."""
    if not p["chamber_id"]:
        return {}
    cr = db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"])
    return sensors.day_averages([d(r["day"]) for r in db.reading_rows(con, pid)], cr)


QUARTERS = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]


def time_axis(first, last) -> alt.Axis:
    """One date format on the whole axis ("27 Sep"). Vega's default mixes "Mon 21", "Sep 27" and
    "October" on one axis (owner, 27 Oct). Ticks every day, week or two weeks, by the span shown."""
    days = max((pd.Timestamp(last) - pd.Timestamp(first)).total_seconds() / 86400, 0)
    if days <= 3:
        return alt.Axis(format="%d %b %H:%M", labelOverlap=True, title=None)
    step = 1 if days <= 12 else 7 if days <= 70 else 14
    # fixed steps from the first day (the start of drying): even gaps, e.g. 20 Sep, 27 Sep, 04 Oct
    t, end, ticks = pd.Timestamp(first).normalize(), pd.Timestamp(last), []
    while t <= end:
        ticks.append(alt.DateTime(year=t.year, month=t.month, date=t.day))
        t += pd.Timedelta(days=step)
    return alt.Axis(format="%d %b", values=ticks, labelOverlap=True, title=None)


def left_out_periods(ch, no_data=()):
    """Periods the sensor was out of the chamber, kept per chamber: applied to every import and hub sync
    (full audit 27 Oct, #3), and can be added without uploading a file (#4)."""
    ex = db.exclusions(con, ch["id"])
    with st.expander(f"Left-out periods ({len(ex)})", key=f"exexp{pid}"):
        st.caption("Times the sensor was out of the chamber (in the freezer, on the kitchen table). Readings "
                   "in these periods are never stored, from any import or the hub sync. Adding one also "
                   "removes readings already stored for it, except in finished drying periods.")
        for e in ex:
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            a_, b_ = datetime.fromisoformat(e["start_ts"]), datetime.fromisoformat(e["end_ts"])
            c1.markdown(f"**Left out:** {a_:%d %b %Y %H:%M} to {b_:%d %b %Y %H:%M} ({sensors.span_text(a_, b_)})")
            if c2.button("Remove", key=f"exdel{e['id']}", width="stretch",
                         help="Readings removed earlier don't come back: import the file again"):
                act(db.delete_exclusion, e["id"], success="Left-out period removed")
        # stretches without readings: one click turns one into a left-out period (owner, 28 Oct)
        for i, (a_, b_) in enumerate(no_data):
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.markdown(f"No readings: {a_:%d %b %Y %H:%M} to {b_:%d %b %Y %H:%M} ({sensors.span_text(a_, b_)})")
            if c2.button("Save as left-out", key=f"exgap{pid}_{i}", width="stretch",
                         help="If the sensor was out of the fridge then: readings for this time are never imported"):
                # just inside the readings around the gap: those two readings are real and stay
                act(db.add_exclusion, ch["id"], a_ + timedelta(minutes=1), b_ - timedelta(minutes=1),
                    success="Period left out")
        if ex or no_data:
            st.divider()
        c1, c2, c3, c4 = st.columns(4)
        # quarter-hour list, not st.time_input: that widget crashed on some browser locales
        lo_d = c1.date_input("From", value=None, format="DD/MM/YYYY", key=f"lo_d{pid}")
        lo_t = c2.selectbox("at", QUARTERS, index=0, key=f"lo_t{pid}")
        hi_d = c3.date_input("To", value=None, format="DD/MM/YYYY", key=f"hi_d{pid}")
        hi_t = c4.selectbox("at ", QUARTERS + ["23:59"], index=len(QUARTERS), key=f"hi_t{pid}",
                            help="Inclusive: a reading at exactly this time is left out too")
        lo = datetime.combine(lo_d, datetime.strptime(lo_t, "%H:%M").time()) if lo_d else None
        hi = datetime.combine(hi_d, datetime.strptime(hi_t, "%H:%M").time()) if hi_d else None
        if lo and hi:
            n_ = db.sensor_readings_between(con, ch["id"], lo, hi)
            st.caption(f"{n_} readings stored for this period will be removed." if n_ else
                       "No readings stored for this period yet.")
        if st.button("Leave out this period", key=f"exadd{pid}", disabled=not (lo and hi)):
            act(db.add_exclusion, ch["id"], lo, hi, success="Period left out")


def chamber_section():
    """This batch's own temperature/humidity readings (v0.4.17: one sensor per piece of meat): chart,
    left-out overview, import from the Tapo app, hub sync."""
    ch = con.execute("SELECT * FROM chamber WHERE id=?", (p["chamber_id"],)).fetchone()
    cr = db.chamber_readings(con, ch["id"], p["dry_start"], p["dry_end"])
    blk("Sensor readings" + (f" · Tapo sensor {ch['tapo_name']}" if ch["tapo_name"] else ""))
    # left-out periods (saved) and stretches without readings, within the drying period
    d_start = datetime.combine(d(p["dry_start"]), time.min)
    d_end = min(datetime.combine(d(p["dry_end"]) or db.today(), time(23, 59, 59)), datetime.now(db.TZ).replace(tzinfo=None))
    ex_all = [(datetime.fromisoformat(e["start_ts"]), datetime.fromisoformat(e["end_ts"]))
              for e in db.exclusions(con, ch["id"])]
    ex_in = [(max(a, d_start), min(b, d_end)) for a, b in ex_all if b >= d_start and a <= d_end]
    no_data = [(a, b) for a, b in sensors.gaps(cr, d_start, d_end)
               if not any(ea <= a + timedelta(hours=1) and b - timedelta(hours=1) <= eb for ea, eb in ex_in)]
    # charts stay on screen when there is data; settings, import and remove are folded away below
    if not cr:
        st.caption("No readings yet for the drying period.")
    if cr:
        temps = [c["temp_c"] for c in cr if c["temp_c"] is not None]
        rhs = [c["rh_pct"] for c in cr if c["rh_pct"] is not None]
        VIEWS = {"15 min": 0, "1 hour": 1, "12 hours": 12, "24 hours": 24}
        view = st.segmented_control("Average per", list(VIEWS), default="1 hour", key=f"chview{pid}") or "1 hour"
        hrs = VIEWS[view]
        if hrs == 0:                     # every reading as recorded
            cdf = pd.DataFrame([{"Time": pd.Timestamp(c["ts"]), "t": c["temp_c"], "h": c["rh_pct"]} for c in cr])
            cdf = cdf.sort_values("Time")
            gap = pd.Timedelta(hours=1)
        else:                            # block averages, plotted mid-block (24 h: at 12:00, like the weigh-ins)
            cdf = pd.DataFrame([{"Time": pd.Timestamp(b["mid"]), "t": b["t"], "t_min": b["t_min"],
                                 "t_max": b["t_max"], "h": b["h"], "h_min": b["h_min"], "h_max": b["h_max"],
                                 "n": b["n"]} for b in sensors.aggregate(cr, hrs)])
            gap = pd.Timedelta(hours=hrs * 1.5)
        # a new segment after every gap, so lines don't bridge periods without data
        cdf["seg"] = (cdf["Time"].diff() > gap).cumsum()
        match = weigh_in_climate()
        wdf = pd.DataFrame([{"Time": pd.Timestamp(sensors.weigh_in_time(d(r["day"]))),
                             "Weigh-in": f"{fmt_date(r['day'])}: {r['gross_g']:.0f} g",
                             "t": (match.get(d(r["day"])) or (None, None))[0],
                             "h": (match.get(d(r["day"])) or (None, None))[1]}
                            for r in db.reading_rows(con, pid)])
        c1, c2 = st.columns(2)
        for col, field, title, colour in ((c1, "t", "Temperature [°C]", RED), (c2, "h", "Humidity [%]", GREEN)):
            sub = cdf.dropna(subset=[field])
            if not len(sub):
                continue
            fmt = ".1f" if field == "t" else ".0f"
            tip = [alt.Tooltip("Time:T", format="%d %b %H:%M" if hrs < 24 else "%d %b"),
                   alt.Tooltip(f"{field}:Q", title=("average" if hrs else title), format=fmt)]
            if hrs:
                tip += [alt.Tooltip(f"{field}_min:Q", title="lowest", format=fmt),
                        alt.Tooltip(f"{field}_max:Q", title="highest", format=fmt),
                        alt.Tooltip("n:Q", title="readings")]
            layers = []
            if ex_in:                    # left-out periods as grey bands (owner, 28 Oct)
                layers.append(alt.Chart(pd.DataFrame([{"a": a, "b": b, "Left out": f"{a:%d %b %H:%M} to {b:%d %b %H:%M}"}
                                                      for a, b in ex_in])).mark_rect(color=MUTED, opacity=0.18).encode(
                    x=alt.X("a:T", title=None, axis=time_axis(cdf["Time"].min(), cdf["Time"].max())),
                    x2="b:T", tooltip=["Left out:N"]))
            if hrs:                      # lowest–highest band behind the average
                layers.append(alt.Chart(sub).mark_area(color=colour, opacity=0.15).encode(
                    x="Time:T", y=f"{field}_min:Q", y2=f"{field}_max:Q", detail="seg:N"))
            layers.append(alt.Chart(sub).mark_line(
                color=colour, strokeWidth=1.6 if hrs else 1.2,
                point=alt.OverlayMarkDef(color=colour, size=22) if hrs >= 12 else False).encode(
                x=alt.X("Time:T", title=None, axis=time_axis(cdf["Time"].min(), cdf["Time"].max())),
                y=alt.Y(f"{field}:Q", title=title, scale=alt.Scale(zero=False),
                        axis=alt.Axis(format=fmt)),          # constant humidity showed "80.000000"
                detail="seg:N", tooltip=tip))
            layers.append(alt.Chart(wdf).mark_rule(color=MUTED, strokeDash=[3, 3], strokeWidth=1).encode(
                x="Time:T", tooltip=["Weigh-in:N"]))
            layers.append(alt.Chart(wdf.dropna(subset=[field])).mark_point(
                color=INK, filled=True, size=45).encode(
                x="Time:T", y=alt.Y(f"{field}:Q", axis=alt.Axis(format=fmt)),
                tooltip=["Weigh-in:N", alt.Tooltip(f"{field}:Q", title="day average", format=fmt)]))
            col.altair_chart(alt.layer(*layers).properties(height=220), width="stretch")
        st.caption(("Line: average per " + view + "; shaded: lowest to highest in that period. " if hrs else
                    "Every reading as recorded. ")
                   + "Dashed lines: weigh-ins (shown at 12:00). Dots: that day's average, the values in the "
                     "weigh-in table.")
        bits = []
        if temps:
            bits.append(f"temperature {min(temps):.1f} to {max(temps):.1f} °C, average {sum(temps)/len(temps):.1f}")
        if rhs:
            bits.append(f"humidity {min(rhs):.0f} to {max(rhs):.0f} %, average {sum(rhs)/len(rhs):.0f}")
        for n_ in safety.chamber_warnings(cr, KIND or "fridge")[1]:
            st.info(n_, icon=":material/ac_unit:")
        st.caption(f"{len(cr)} readings since drying started: {'; '.join(bits)}. Last reading {fmt_date(cr[-1]['ts'][:10])} "
                   f"{cr[-1]['ts'][11:16]}.")
    # overview, always visible: what is left out and where readings are missing
    if ex_in or no_data:
        st.caption("  \n".join(
            [f"**Left out** (grey on the charts): {a:%d %b %H:%M} to {b:%d %b %H:%M}, {sensors.span_text(a, b)}"
             for a, b in ex_in]
            + [f"**No readings**: {a:%d %b %H:%M} to {b:%d %b %H:%M}, {sensors.span_text(a, b)}"
               + ("" if closed else " (save it as left-out under Sensor settings if the sensor was out)")
               for a, b in no_data]))
    if closed:
        return
    # fixed title + key: a changing title would make the section close on every rerun
    with st.expander("Sensor settings, import and remove", key=f"chamber_exp{pid}"):
        kinds = list(safety.KINDS)
        dry_done = bool(p["dry_locked_at"])
        new_kind = st.segmented_control(
            "Type", kinds, default=KIND or ch["kind"] or "fridge", key=fresh(f"chkind{pid}", ch["kind"] or "fridge"), disabled=closed or dry_done,
            format_func=lambda k_: f"{safety.KINDS[k_]} (warn above {safety.TEMP_MAX[k_]:g} °C)",
            help="Where this batch dries: sets which temperature rules apply.")
        if dry_done:
            st.caption("Drying is locked, so this batch keeps its type. Unlock drying to change it.")
        elif new_kind and new_kind != (ch["kind"] or "fridge"):
            act(db.set_chamber_kind, ch["id"], new_kind, success=f"Drying in a {safety.KINDS[new_kind].lower()}")
        c1_, c2_ = st.columns([3, 1], vertical_alignment="bottom")
        tn = c1_.text_input("Tapo sensor name", value=ch["tapo_name"] or "", key=fresh(f"tapon{pid}", ch["tapo_name"] or ""),
                            placeholder="as in the Tapo app", help="Only for the hub sync: the sync fills this batch's "
                            "readings from the sensor with this name.")
        if c2_.button("Save name", key=f"taposave{pid}", width="stretch",
                      disabled=(tn.strip() or None) == (ch["tapo_name"] or None)):
            act(db.set_tapo_name, ch["id"], tn, success="Tapo sensor name saved")
        st.markdown("**Import from the Tapo app**")
        st.caption("In the Tapo app: sensor → History → View All → download icon → pick interval and range. "
                   "Attach the file from the e-mail here. Readings already here are kept and only new times are "
                   "added, so the next, longer export simply fills in the rest. If the sensor was out of the "
                   "fridge, add that time under Left-out periods (below): it is skipped in every later import.")
        up = st.file_uploader("Tapo export", type=["csv", "xlsx", "xlsm"], key=f"tapo{pid}{st.session_state.get('tapo_n', 0)}",
                              label_visibility="collapsed")
        if up is not None:
            try:
                parsed = sensors.parse_export(up.getvalue(), up.name)
            except ValueError as e:
                st.error(md(e))
                parsed = None
            if parsed:
                rows_, n_ex, n_lk = sensors.protected(con, ch["id"], parsed.rows)
                skip = "; ".join(x for x in (f"{n_ex} in left-out periods" if n_ex else "",
                                             f"{n_lk} in finished drying periods" if n_lk else "") if x)
                have = sensors.existing_times(con, ch["id"], "tapo_export", rows_)
                n_have = sum(1 for r_ in rows_ if r_[0].isoformat(timespec="seconds") in have)
                replace = st.checkbox("Replace readings that are already there", key=f"taporep{pid}",
                                      help="Normally kept. Tick only if the stored values are wrong.") if n_have else False
                if not rows_ or (n_have == len(rows_) and not replace):
                    st.warning("Nothing new to import" + (f": all {n_have} readings are already there" if n_have else "")
                               + (f" ({skip} are skipped)." if skip else "."))
                else:
                    temps = [t for _, t, _ in rows_ if t is not None]
                    rhs = [h for _, _, h in rows_ if h is not None]
                    st.info(f"**{len(rows_) - n_have} new readings**"
                            + (f", {n_have} already there ({'replaced' if replace else 'kept'})" if n_have else "")
                            + f". File from {rows_[0][0]:%d %b %Y %H:%M} to "
                            f"{rows_[-1][0]:%d %b %Y %H:%M}"
                            + (f"; temperature {min(temps):.1f} to {max(temps):.1f} °C" if temps else "")
                            + (" (converted from °F)" if parsed.fahrenheit else "")
                            + (f"; humidity {min(rhs):.0f} to {max(rhs):.0f} %" if rhs else "")
                            + (f". Skipped: {skip}" if skip else "")
                            + (f". {parsed.skipped} lines unreadable." if parsed.skipped else "."))
                    if st.button("Import", type="primary", key=f"tapoimp{pid}"):
                        with con:
                            res = sensors.import_export(con, ch["id"], parsed.rows, replace=replace)
                        st.session_state["tapo_n"] = st.session_state.get("tapo_n", 0) + 1   # empty the uploader
                        st.session_state["flash"] = (f"{res.stored} new readings imported"
                                                     + (f", {res.existing} already there "
                                                        f"{'replaced' if replace else 'kept'}" if res.existing else "")
                                                     + (f", {res.rejected} out of range skipped" if res.rejected else ""))
                        st.rerun()
        left_out_periods(ch, no_data)
        counts = db.chamber_reading_counts(con, ch["id"])
        if counts:
            with st.expander("Remove readings (e.g. imported the wrong file)"):
                srcs = list(counts)
                src = st.selectbox("Which readings", srcs, key=f"rm_src{pid}", format_func=lambda s_: (
                    f"{db.SOURCE_NAMES.get(s_, s_)}: {counts[s_][0]} readings, "
                    f"{fmt_date(counts[s_][1][:10])} to {fmt_date(counts[s_][2][:10])}"))
                c1, c2 = st.columns(2)
                rm_a = c1.date_input("Only from (optional)", value=None, format="DD/MM/YYYY", key=f"rm_a{pid}")
                rm_b = c2.date_input("Only to (optional)", value=None, format="DD/MM/YYYY", key=f"rm_b{pid}")
                locked = db.locked_periods(con, ch["id"])
                if locked:
                    st.caption("Kept in any case, because their drying is locked: " + "; ".join(
                        f"{md(r['name'])} ({fmt_date(r['dry_start'])} to {fmt_date(r['dry_end'])})" for r in locked) + ".")
                sure = st.checkbox("Remove them from this batch", key=f"rm_ok{pid}")
                if st.button("Remove readings", disabled=not sure, key=f"rm_b_{pid}"):
                    with con:
                        n, kept = db.delete_chamber_readings(con, ch["id"], src,
                                                             datetime.combine(rm_a, time.min) if rm_a else None,
                                                             datetime.combine(rm_b, time(23, 59, 59)) if rm_b else None)
                    st.session_state["flash"] = (f"Removed {n} readings"
                                                 + (f"; kept {kept} from locked drying periods" if kept else "")
                                                 + ". Import the right file now.")
                    st.rerun()
        if tapo_sync.is_configured():
            st.markdown("**Straight from the hub**")
            st.caption("The hub keeps the last 24 hours. A daily scheduled sync (see docs/NAS.md) keeps the history "
                       "complete. It fills every drying batch that has a Tapo sensor name (above)"
                       + ("." if tapo_sync.hub_fed(ch) else "; this batch has none yet."))   # full audit #7
            if st.button("Sync last 24 h from hub", key=f"tapohub{pid}"):
                with st.spinner("Reading the hub..."):
                    res = tapo_sync.sync(con)
                errs = [f"{md(r.chamber)}: {md(r.error)}" for r in res if r.error]
                if not res:
                    st.session_state["flash_error"] = ("No batch is drying with a Tapo sensor name: "
                                                       "add it under Sensor settings first.")
                elif errs:
                    st.session_state["flash_error"] = "Hub sync failed. " + "; ".join(errs)
                else:
                    st.session_state["flash"] = "; ".join(f"{md(r.chamber)}: {r.stored} readings"
                                                             + (f", {r.skipped} skipped (left-out or finished "
                                                                "drying period)" if r.skipped else "") for r in res)
                st.rerun()


def step_dry():
    if not p["dry_start"]:
        step_dry_start()
        return
    d_locked = bool(p["dry_locked_at"]) or closed
    s = db.drying_status(con, pid)
    eta = s["eta"]
    rows = db.reading_rows(con, pid)

    # --- weigh-in: the daily action, first ----------------------------------- #
    if not d_locked:
        blk("Weigh-in")
        with st.form(f"reading{pid}", clear_on_submit=True):
            c1, c2, c3 = st.columns([1.2, 1.4, 1], vertical_alignment="bottom")
            rd = c1.date_input("Date", value=db.today(), format="DD/MM/YYYY")
            rw = c2.number_input("Weight incl. wrap + net [g]", min_value=1.0, value=None, step=1.0,
                                 format="%.0f", placeholder=f"last: {s['latest_gross_g']:.0f}")
            submit = c3.form_submit_button("Save weigh-in", type="primary", width="stretch")
            with st.expander("More: temperature, humidity, note"):
                e1, e2 = st.columns(2)
                rt = e1.number_input("Chamber temperature [°C]", value=None, step=0.1, placeholder="optional",
                                     min_value=db.TEMP_RANGE[0], max_value=db.TEMP_RANGE[1])
                rh = e2.number_input("Chamber humidity [%]", value=None, step=1.0, placeholder="optional",
                                     min_value=db.RH_RANGE[0], max_value=db.RH_RANGE[1])
                rn = st.text_input("Note", placeholder="smell, firmness, mould")
            if submit:
                if rw is None:
                    st.error("Enter the weight.")
                else:
                    errors, warns = db.reading_problems(con, pid, rd, rw)
                    pending = dict(day=rd, weight=rw, temp=rt, rh=rh, note=rn or None)
                    if errors:
                        st.error(" ".join(errors))
                    elif warns:
                        st.session_state[f"pending{pid}"] = (pending, warns)
                        st.rerun()
                    else:
                        save_weigh_in(pending)
        if f"pending{pid}" in st.session_state:
            pending, warns = st.session_state[f"pending{pid}"]
            st.warning("**Check this weigh-in before saving.**  \n" + "  \n".join(warns))
            c1, c2, _ = st.columns([1.3, 1, 3])
            if c1.button("Save anyway", type="primary", key=f"pend_ok{pid}", width="stretch"):
                del st.session_state[f"pending{pid}"]
                save_weigh_in(pending, confirmed=True)
            if c2.button("Cancel", key=f"pend_no{pid}", width="stretch"):
                del st.session_state[f"pending{pid}"]
                st.rerun()

    # --- result band ------------------------------------------------------------ #
    blk("Where it stands")
    m = st.columns(5)
    m[0].metric("Latest weight", f"{s['latest_gross_g']:.0f} g", help=f"on {s['latest_day']:%d %b %Y}")
    m[1].metric("Target weight", f"{s['target_gross_g']:.0f} g",
                help=f"{p['target_loss_pct']:g} % loss on the meat at the start of drying, plus packaging")
    m[2].metric("Weight lost", f"{s['loss_pct']:.1f} %",
                help="Of the meat at the start of drying (start weight minus packaging). Stricter than measuring "
                     "from the raw weight, because the meat already loses some weight in the bag.")
    if w_ := safety.target_message(float(p["target_loss_pct"])):
        st.warning(w_)
    m[3].metric("Progress to target", f"{min(s['progress'], 1)*100:.0f} %")
    if s["progress"] >= 1:
        eta_txt, eta_help = "Reached", "The latest weigh-in is at or below the target weight."
    elif eta:
        fmt_ = lambda d_: d_.strftime("%d %b" if d_.year == db.today().year else "%d %b %Y")
        eta_txt = fmt_(eta.eta_date)
        all_ = s.get("eta_all")
        eta_help = (f"At the pace of the last {calc.RECENT_DAYS} days ({eta.grams_per_day:.1f} g/day). "
                    + (f"A line through all weigh-ins says {fmt_(all_.eta_date)} ({all_.grams_per_day:.1f} g/day); "
                       if all_ else "")
                    + "drying keeps slowing, so the real date is usually later still.")
    else:
        eta_txt, eta_help = "–", "Needs 2+ weigh-ins, losing weight"
    m[4].metric("Estimated finish", eta_txt, help=eta_help)
    st.progress(min(max(s["progress"], 0.0), 1.0))

    # --- what happened ---------------------------------------------------------- #
    blk("What happened")
    rdf = pd.DataFrame([{"Date": pd.Timestamp(r["day"]), "Weight (g)": r["gross_g"]} for r in rows])
    line = alt.Chart(rdf).mark_line(point=True, color=RED).encode(
        # ticks on the weigh-in days, the dates that matter here; with many weigh-ins every 7 or 14 days
        x=alt.X("Date:T", title=None, axis=alt.Axis(
            format="%d %b", labelOverlap=True,
            values=[alt.DateTime(year=t.year, month=t.month, date=t.day) for t in rdf["Date"]])
            if len(rdf) <= 12 else time_axis(rdf["Date"].min(), rdf["Date"].max())),
        y=alt.Y("Weight (g):Q", title="Weight incl. wrap + net [g]", scale=alt.Scale(
            zero=False, domain=[min(s["target_gross_g"], rdf["Weight (g)"].min()) * 0.97,
                                max(s["start_gross_g"], rdf["Weight (g)"].max()) * 1.01])),
        tooltip=[alt.Tooltip("Date:T", format="%d %b %Y"), "Weight (g):Q"])
    target = alt.Chart(pd.DataFrame({"t": [s["target_gross_g"]]})).mark_rule(
        strokeDash=[6, 4], color=INK).encode(y=alt.Y("t:Q", title="Weight incl. wrap + net [g]"))
    # label on the target line (owner, 28 Oct), at the left end: the weight is highest there, so the
    # data line never runs through the text
    tlabel = alt.Chart(pd.DataFrame({"Date": [rdf["Date"].min()], "t": [s["target_gross_g"]],
                                     "label": [calc.target_label(s["target_gross_g"], p["target_loss_pct"])]})).mark_text(
        align="left", baseline="bottom", dx=4, dy=-4, color=INK, fontSize=12).encode(
        x="Date:T", y="t:Q", text="label:N")
    # chart full width, then the weigh-in table full width (it has 10 columns)
    st.altair_chart(alt.layer(line, target, tlabel).properties(height=280), width="stretch")
    match = weigh_in_climate()
    per = weigh_in_periods()
    # weigh-in notes as numbered footnotes below the table (owner, 28 Oct): a note column cuts them off
    noted = [r for r in rows if (r["note"] or "").strip()]
    notes_no = {r["day"]: str(i) for i, r in enumerate(noted, 1)}
    tdf = pd.DataFrame([{
        "Date": d(r["day"]).strftime("%d %b"), "Day": (d(r["day"]) - d(p["dry_start"])).days,
        "Weight [g]": int(r["gross_g"]),
        "Lost [%]": round(calc.loss_pct(s["start_gross_g"], r["gross_g"], p["tare_g"]), 1),
        "Day °C": climate_cell(match.get(d(r["day"])), 0),
        "Day RH [%]": climate_cell(match.get(d(r["day"])), 1),
        "Since last °C": period_cell(per.get(d(r["day"])), 0),
        "Since last RH [%]": period_cell(per.get(d(r["day"])), 1),
        "Data [%]": f"{per[d(r['day'])][4] * 100:.0f}" if per.get(d(r["day"])) else "–",
        "Footnote": notes_no.get(r["day"], "")} for r in rows])
    left = "left"            # owner 27 Oct: every value aligned left, like the headings
    st.dataframe(tdf, hide_index=True, width="stretch", height=min(38 + 35 * len(tdf), 420), column_config={
        "Date": st.column_config.TextColumn(alignment=left),
        "Day": st.column_config.NumberColumn(alignment=left),
        "Weight [g]": st.column_config.NumberColumn(alignment=left),
        "Lost [%]": st.column_config.NumberColumn(alignment=left),
        "Day °C": st.column_config.TextColumn(alignment=left, help="Average of all chamber readings on the weigh-in day. "
                                              "* = the sensor reported for less than half the day."),
        "Day RH [%]": st.column_config.TextColumn(alignment=left, help="Day average, as for Day °C."),
        "Since last °C": st.column_config.TextColumn(alignment=left, help="Average since the previous weigh-in (12:00 to "
                                                     "12:00): the conditions behind this weight loss."),
        "Since last RH [%]": st.column_config.TextColumn(alignment=left, help="Average since the previous weigh-in."),
        "Data [%]": st.column_config.TextColumn(alignment=left, help="Share of hours since the previous weigh-in with "
                                                "sensor readings. Under 50 % the averages get a *."),
        "Footnote": st.column_config.TextColumn(alignment=left, help="Number of the weigh-in note below the table")})
    if noted:                # same small size as the legend below (owner, 28 Oct)
        st.caption("  \n".join(f"**{i}** · {fmt_date(r['day'])}: {md(' '.join(r['note'].split()))}"
                                for i, r in enumerate(noted, 1)))
    st.caption("Day: average on the weigh-in day. Since last: average since the previous weigh-in, the "
               "conditions behind that weight loss. * less than half the time covered by sensor data; – none; "
               f"⚠ outside the safe range for a {safety.KINDS[KIND or 'fridge'].lower()} (above "
               f"{safety.TEMP_MAX[KIND or 'fridge']:g} °C, humidity outside "
               f"{safety.RH_MIN:g}-{safety.RH_MAX:g} %).")
    if p["chamber_id"]:
        cr_dry = db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"])
        for w_ in safety.chamber_warnings(cr_dry, KIND or "fridge")[0]:
            st.warning(w_, icon=":material/thermostat:")
        chamber_section()
    if not d_locked and len(rows) > 1:
        with st.expander("Delete a weigh-in"):
            choice = st.selectbox("Weigh-in", [r["day"] for r in rows[1:]], format_func=fmt_date)
            if st.button("Delete"):
                act(db.delete_reading, pid, choice, success="Deleted")

    note = journal("dry", p["dry_note"], db.set_dry_note,
                   "e.g. wrap doubled on one side; white bloom on day 30")

    # --- setup (folded away) ------------------------------------------------------ #
    blk("Setup")
    mismatch = bool(p["cure_end_actual"] and p["dry_start"] != p["cure_end_actual"])
    if mismatch:
        st.warning(f"Drying starts on {fmt_date(p['dry_start'])}, but the meat came out of the bag on "
                   f"{fmt_date(p['cure_end_actual'])}. If that is wrong, correct the start below.")
    with st.expander("Drying start, packaging and target", expanded=mismatch):
        with st.form(f"drystartedit{pid}", border=False):
            c1, c2, c3, c4 = st.columns([1.2, 1.3, 1.3, 1.2], vertical_alignment="bottom")
            es = c1.date_input("Drying start", value=d(p["dry_start"]), format="DD/MM/YYYY", disabled=d_locked)
            eg = c2.number_input("Start weight incl. wrap + net [g]", min_value=1.0, format="%.0f",
                                 value=float(p["dry_start_gross_g"]), step=1.0, disabled=d_locked)
            et = c3.number_input("Packaging: wrap + net [g]", min_value=0.0, format="%.0f",
                                 value=float(p["tare_g"] or 0), step=1.0, disabled=d_locked)
            ee = c4.checkbox("Packaging is an estimate", value=bool(p["tare_estimated"]), disabled=d_locked)
            if st.form_submit_button("Save drying start", disabled=d_locked):
                act(db.update_drying_start, pid, start=es, start_gross_g=eg, tare_g=et,
                    tare_estimated=ee, success="Drying start updated")
        st.divider()
        c1, c2, c3 = st.columns([1, 2, 1], vertical_alignment="bottom")
        stored = float(p["target_loss_pct"])
        if safety.target_problem(stored):          # set before v0.4.0, when 1-70 % was allowed
            st.error(f"The current target ({stored:g} %) is outside the allowed "
                     f"{safety.TARGET_MIN:g}-{safety.TARGET_MAX:g} %. Set a new one.")
        nt = c1.number_input("Target loss [%]", min_value=safety.TARGET_MIN, max_value=safety.TARGET_MAX,
                             disabled=d_locked, step=0.5, key=fresh(f"tgt{pid}", stored),
                             value=min(max(stored, safety.TARGET_MIN), safety.TARGET_MAX),
                             help=f"Allowed {safety.TARGET_MIN:g}-{safety.TARGET_MAX:g} %. " "Measured on the meat at the start of drying: start weight minus packaging.")
        # a stored out-of-range target shows its one error above; the clamped default adds no second message
        if (w_ := safety.target_warning(nt)) and not (safety.target_problem(stored)
                                                      and nt == min(max(stored, safety.TARGET_MIN), safety.TARGET_MAX)):
            st.warning(w_)
        why = c2.text_input("Reason for change", key=f"why{pid}", disabled=d_locked)
        if c3.button("Change target", disabled=d_locked or nt == p["target_loss_pct"], width="stretch"):
            act(db.change_target, pid, nt, why, success="Target changed")

    # --- done ------------------------------------------------------------------------ #
    blk("Done")
    if closed:
        return
    if not p["dry_locked_at"]:
        c1, c2, _ = st.columns([1.2, 2.2, 3], vertical_alignment="bottom")
        de = c1.date_input("Drying ended", value=d(p["dry_end"]) or db.today(), format="DD/MM/YYYY", key=f"de{pid}")

        short = db.below_target(con, pid)
        short_ok = False
        if short:
            st.warning(f"The last weigh-in is at {short[0]:.1f} % weight loss, below the {short[1]:g} % target. "
                       "Ending now is your choice; it is noted in the history and in the PDF.")
            short_ok = st.checkbox("End drying below the target", key=f"dshort{pid}")

        def note_and_lock(con_, pid_):
            db.set_dry_note(con_, pid_, note.strip())
            db.lock_dry(con_, pid_, de, below_target_ok=short_ok)
        if c2.button("Done: lock drying and finish", type="primary", key=f"dlk{pid}", width="stretch",
                     disabled=bool(short) and not short_ok):
            act(note_and_lock, pid, success="Drying locked", goto="finish")
    else:
        st.caption(f"Drying ended {fmt_date(p['dry_end'])}.")
        unlock_panel("dry", p["dry_locked_at"], db.unlock_dry, "Drying")


# --------------------------------------------------------------------------- #
# step 4: finish
# --------------------------------------------------------------------------- #

def step_finish():
    rs = db.readings(con, pid)
    if p["dry_start"] and rs:
        final_g = rs[-1][1]
        dry_days = ((d(p["dry_end"]) or db.today()) - d(p["dry_start"])).days
        cure_days = (d(p["cure_end_actual"]) - d(p["cure_start"])).days if p["cure_end_actual"] else None
        total_days = ((d(p["dry_end"]) or db.today()) - d(p["start_date"])).days
        lost = p["dry_start_gross_g"] - final_g
        band([("Final weight" if p["dry_end"] else "Weight now", f"{final_g:.0f} g",
               "last weigh-in, incl. wrap + net"),
              ("Lost while drying", f"{lost:.0f} g",
               f"{calc.loss_pct(p['dry_start_gross_g'], final_g, p['tare_g']):.1f} % of the meat at the start of drying"),
              ("Final ÷ raw meat" if p["dry_end"] else "Now ÷ raw meat",
               f"{100 * (final_g - (p['tare_g'] or 0)) / p['green_weight_g']:.0f} %",
               f"meat only, without wrap + net; raw {p['green_weight_g']:.0f} g"),
              ("Cure", f"{cure_days} days" if cure_days is not None else "–", "in the bag"),
              ("Drying", f"{dry_days} days", "so far" if not p["dry_end"] else "wrapped and netted"),
              ("Total", f"{total_days} days", "from day 0")])
        if p["dry_end"] and (short := db.below_target(con, pid)):
            st.warning(safety.below_target_message(*short))
    else:
        st.info("The result appears here once drying has started.")

    blk("PDF summary")
    c1, c2 = st.columns([1.3, 3], vertical_alignment="center")
    c1.download_button("Download PDF summary" if closed else "Download summary so far (PDF)",
                       lambda pid_=pid: report.build_pdf_standalone(pid_),   # built on click, in another thread
                       file_name=report.file_name(p), mime="application/pdf",
                       key=f"pdf{pid}", type="primary" if closed else "secondary", width="stretch")
    c2.caption("Result, timeline, recipe, cure, drying chart and weigh-ins, notes and photos. "
               + ("" if closed else "Download it again after closing for the final version."))

    if closed:
        st.success(f"Closed on {fmt_date(p['closed_at'][:10])}. This project is read-only.")
        if p["final_notes"]:
            blk("Final notes")
            st.markdown(md_text(p["final_notes"]))
    else:
        blk("Close the batch")
        missing = db.close_problems(con, pid)
        if missing:
            st.info("Before this batch can be closed: " + "; ".join(missing) + ".")
        st.caption("Closing makes the project read-only. The PDF summary above then becomes the final version.")
        with st.form(f"close{pid}"):
            fn = st.text_area("Final notes: texture, taste, what to change next time", height=120)
            sure = st.checkbox("I understand the project becomes read-only")
            if st.form_submit_button("Close project", type="primary", disabled=bool(missing)):
                if not sure:
                    st.error("Tick the box to confirm")
                else:
                    act(db.close_project, pid, fn, success="Project closed")

    allp = db.photos(con, pid)
    if allp:
        blk("All photos")
        for stage in ("spice", "cure", "dry", "equalise", None):
            rows = [r for r in allp if r["stage"] == stage]
            if rows:
                st.markdown(f"**{STAGE_NAME[stage]}**")
                show_photos(rows)

    blk("Project")
    with st.expander("History"):
        ev = db.events(con, pid)
        st.dataframe(pd.DataFrame([{"When": e["ts"].replace("T", " "), "What": e["kind"].replace("_", " "),
                                    "Detail": e["detail"] or ""} for e in ev]),
                     hide_index=True, width="stretch")
    st.caption("Rename or delete the project from the menu under the project list in the sidebar.")


{"day0": step_day0, "cure": step_cure, "dry": step_dry, "finish": step_finish}[sel]()
