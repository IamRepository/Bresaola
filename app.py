"""Bresaola Tracker – Streamlit UI.

The batch is shown as a journey: Day 0 (spice and bag) → Cure → Dry → Finish.
Every step is built from the same blocks, in the same order:
    next action → result band → what happened → journal (notes + photos) → setup → Done
Done locks the step and opens the next one.

Run:  streamlit run app.py
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from bresaola import __version__, calc, db, storage
from bresaola.blends import BLENDS
from bresaola.demo import seed_demo

st.set_page_config(page_title="Bresaola Tracker", page_icon="🥩", layout="wide")

RED, RED_BG, GREEN, GREEN_BG, INK, MUTED, LINE = (
    "#7a2320", "#f6ece9", "#3e5a44", "#f1f6f1", "#2e2a28", "#7d7672", "#e3dedb")

st.markdown(f"""<style>
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{ height: 2.25rem; padding: .5rem 1rem 0; }}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding-top: 0; }}
section[data-testid="stSidebar"] h1 {{ padding-top: 0; }}
.block-container {{ padding-top: 1.2rem; max-width: 1150px; }}
.block-container h2 {{ padding-top: 0; }}
section[data-testid="stSidebar"] .st-key-testmode [data-testid="stAlert"] p {{ font-size: .82rem; }}

/* journey rail */
.st-key-rail [data-testid="stHorizontalBlock"] {{ gap: .5rem; }}
.st-key-rail button {{ height: auto; min-height: 3.6rem; padding: .55rem .8rem; border-radius: 8px;
  justify-content: flex-start; text-align: left; border: 1px solid #d9d4d0; background: #fff; color: #8a8480; }}
.st-key-rail button p {{ font-weight: 500; font-size: .98rem; text-align: left; line-height: 1.25; }}
.st-key-rail button:hover {{ border-color: {RED}; color: {RED}; }}
.stat {{ margin: .4rem .1rem 0; line-height: 1.35; }}
.stat .tag {{ display:inline-block; font-size:.68rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
  padding:.12rem .45rem; border-radius:4px; margin-right:.35rem; vertical-align:1px; }}
.stat .main {{ font-size:.86rem; font-weight:600; color:{INK}; }}
.stat .more {{ display:block; font-size:.8rem; color:{MUTED}; margin-top:.1rem; }}
.stat .more.due {{ color:{RED}; font-weight:600; }}
.stat.done .tag {{ background:{GREEN_BG}; color:{GREEN}; border:1px solid #c9dacb; }}
.stat.now .tag {{ background:{RED}; color:#fff; }}
.stat.wait .tag {{ background:#f1efee; color:#8a8480; }}
.stat.wait .main {{ color:#8a8480; font-weight:500; }}

/* bands: summary figures at the top of each step */
.band {{ border:1px solid {LINE}; border-radius:10px; padding:1rem 1.25rem .9rem; margin: .25rem 0 1rem; }}
.band .grid {{ display:grid; grid-template-columns:repeat(var(--cols,3),minmax(0,1fr)); column-gap:1.5rem; row-gap:.85rem; }}
.band .lab {{ font-size:.8rem; color:{MUTED}; margin-bottom:.1rem; }}
.band .val {{ font-size:1.4rem; font-weight:600; color:{INK}; line-height:1.2; }}
.band .sub {{ font-size:.8rem; color:{MUTED}; }}
.band .chip {{ font-size:.75rem; padding:.1rem .5rem; border-radius:4px; margin-left:.4rem; vertical-align:middle; font-weight:500; }}
.band .chip.ok {{ background:{GREEN_BG}; color:{GREEN}; }}
.band .chip.over {{ background:{RED_BG}; color:{RED}; }}
.band .chip.run {{ background:#f1efee; color:#5f5955; }}
.band .track {{ position:relative; height:8px; background:#f1efee; border-radius:4px; margin-top:1rem; }}
.band .fill {{ position:absolute; left:0; top:0; bottom:0; background:{RED}; border-radius:4px; }}
.band .mark {{ position:absolute; top:-5px; width:4px; height:18px; background:#fff; border:1.5px solid {INK};
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
        st.error(str(e))
        return False
    except sqlite3.IntegrityError as e:   # safety net; db functions check first
        st.error(f"Could not save: {e}")
        return False
    if success:
        st.session_state["flash"] = success
    if goto:
        st.session_state[f"step{pid}"] = goto
    st.rerun()


def blk(title: str):
    st.markdown(f'<div class="blk">{title}</div>', unsafe_allow_html=True)


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
    st.title("Bresaola Tracker")
    st.caption(f"v{__version__}  \nCredit to Eric Pousson from 2 Guys & A Cooler")

    projs = db.projects(con)
    labels = {p["id"]: db.display_name(p) + ("  (closed)" if p["status"] == "closed" else "") for p in projs}
    if projs:
        default = st.session_state.get("pid", projs[0]["id"])
        ids = list(labels)
        pid = st.selectbox("Project", ids, index=ids.index(default) if default in ids else 0,
                           format_func=labels.get)
        st.session_state["pid"] = pid
        sp = db.project(con, pid)
        with st.popover("Rename or delete", icon=":material/more_horiz:", width="stretch"):
            st.markdown("**Rename**")
            new_name = st.text_input("New name", value=sp["name"], key=f"rn{pid}",
                                     help="The date in front comes from the start date and is added automatically.")
            if st.button("Rename", disabled=sp["status"] == "closed" or new_name.strip() in ("", sp["name"]),
                         key=f"rnb{pid}", width="stretch"):
                act(db.rename_project, pid, new_name, success="Renamed")
            st.divider()
            st.markdown("**Delete**")
            st.caption("Removes this project, its weigh-ins and photos for good. The drying chamber and its "
                       "readings stay. Download a backup first if you might want it back.")
            confirm = st.text_input(f"Type **{sp['name']}** to confirm", key=f"del{pid}")
            if st.button("Delete project permanently", disabled=confirm.strip() != sp["name"],
                         key=f"delb{pid}", width="stretch"):
                with con:
                    db.delete_project(con, pid)
                storage.delete_project_photos(pid)
                st.session_state.pop("pid", None)
                st.session_state["flash"] = f"Deleted {sp['name']}"
                st.rerun()
    else:
        pid = None

    with st.expander("New project", expanded=not projs):
        with st.form("new_project", clear_on_submit=True):
            name = st.text_input("Name", placeholder="Valtellina Nov 2026")
            start_d = st.date_input("Start date", value=db.today(), format="DD/MM/YYYY",
                                    help="Day 0: the day the meat is trimmed, spiced and bagged")
            weight = st.number_input("Meat weight [g]", min_value=1.0, value=2000.0, step=1.0, format="%.0f",
                                     help="Raw meat after trimming")
            if st.form_submit_button("Create project", type="primary"):
                if not name.strip():
                    st.error("Give the project a name")
                else:
                    try:
                        with con:
                            new = db.create_project(con, name.strip(), next(iter(BLENDS)), False, weight, start_d)
                        st.session_state["pid"] = new
                        st.session_state[f"step{new}"] = "day0"
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    st.divider()
    with st.expander("Data: backup and restore"):
        st.download_button("Download backup", storage.make_backup,   # built only when clicked
                           file_name=f"bresaola-backup-{db.today().isoformat()}.zip",
                           mime="application/zip", width="stretch")
        with st.popover("Restore backup", width="stretch"):
            st.caption("Replaces **all** projects and photos with the contents of the backup.")
            up = st.file_uploader("Backup file (.zip)", type="zip", key="restore")
            if st.button("Replace all data", type="primary", disabled=up is None, width="stretch"):
                con.close()
                try:
                    storage.restore_backup(up.getvalue())
                    st.session_state.pop("pid", None)
                    st.session_state["flash"] = "Backup restored. Previous data kept in 'before-restore'."
                except ValueError as e:
                    st.session_state["flash_error"] = f"Nothing was changed. {e}"
                except Exception as e:
                    st.session_state["flash_error"] = f"Restore failed, your data is unchanged: {e}"
                st.rerun()
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
st.header(db.display_name(p))
facts = [p["blend"], f"{p['green_weight_g']:.0f} g raw meat after trimming",
         "EcoCure #2" if p["ecocure"] else "no EcoCure", f"started {d(p['start_date']):%d %b %Y}"]
if closed:
    facts.append(f"closed {d(p['closed_at'][:10]):%d %b %Y}")
st.caption(",  ".join(facts))

# --------------------------------------------------------------------------- #
# journey rail
# --------------------------------------------------------------------------- #

STEPS = ["day0", "cure", "dry", "finish"]
TITLE = {"day0": "Day 0: spice and bag", "cure": "Cure", "dry": "Dry", "finish": "Finish"}
done = {"day0": bool(p["spice_locked_at"]), "cure": bool(p["cure_locked_at"]),
        "dry": bool(p["dry_locked_at"]), "finish": closed}
current = next((s for s in STEPS if not done[s]), "finish")


WEIGH_EVERY = 7          # days; weigh-ins are roughly weekly, the reminder shows after 6 days


def short(dt) -> str:
    return f"{dt.day} {dt:%b}"


def step_status(s: str) -> tuple[str, str, str, bool]:
    """(state, main line, second line, second line is a warning) for the status under a rail button.
    state: done, now (the step to work on) or wait."""
    state = "done" if done[s] else ("now" if s == current else "wait")
    today = db.today()
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
        main = f"day {(end - d(p['dry_start'])).days} · {lost:.1f} % of {p['target_loss_pct']:.0f} % lost"
        if done[s]:
            return state, main, "target reached" if st_["progress"] >= 1 else "ended", False
        last = db.readings(con, pid)[-1][0]
        due = last + timedelta(days=WEIGH_EVERY)
        if due <= today:
            return state, main, "weigh-in due", True
        return state, main, f"next weigh-in by {short(due)}", False
    if closed:
        return state, f"closed {short(d(p['closed_at'][:10]))}", "read-only", False
    if state == "now":
        return state, "tasting notes", "then close the batch", False
    return state, "after drying", f"at {p['target_loss_pct']:.0f} % weight loss" if p["dry_start"] else "", False


STATE_LABEL = {"done": "Done", "now": "Now", "wait": "Next"}


def status_html(s: str) -> str:
    state, main, more, warn = step_status(s)
    more_html = f'<span class="more{" due" if warn else ""}">{more}</span>' if more else ""
    return (f'<div class="stat {state}"><span class="tag">{STATE_LABEL[state]}</span>'
            f'<span class="main">{main}</span>{more_html}</div>')


step_key = f"step{pid}"
if step_key not in st.session_state:
    st.session_state[step_key] = current
sel = st.session_state[step_key]

with st.container(key="rail"):
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
                       f"border-color:#9db39f !important; color:{GREEN} !important; }}")
        elif s == current:
            css.append(f"{k}, {k}:hover, {k}:focus {{ border:2px solid {RED} !important; "
                       f"color:{RED} !important; background:#fff !important; }}")
        if s == sel:
            col = GREEN if done[s] else RED
            css.append(f"{k} {{ box-shadow: inset 0 -4px 0 {col} !important; }} {k} p {{ font-weight:700; }}")
    st.markdown("<style>" + "\n".join(css) + "</style>", unsafe_allow_html=True)


def next_action() -> tuple[str | None, bool]:
    """(sentence, is_all_done) describing what to do now for the whole batch.
    sentence is None when there is nothing to do today (drying, weighed within the week)."""
    if closed:
        return "This batch is closed. Everything is read-only.", True
    if current == "day0":
        return ("<b>Day 0:</b> weigh the trimmed meat, choose the blend, weigh out the spices, measure the "
                "piece and seal it in the bag. Then press <b>Done</b>.", False)
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
            st.caption(f"{fmt_date(r['taken_at'][:10])}" + (f", {r['caption']}" if r["caption"] else ""))


def journal(stage: str, note_value: str | None, save_note, placeholder: str) -> str:
    """Notes and photos for one step. Always open unless the project is closed.
    Returns the note text currently on screen (callers may save it with Done)."""
    blk("Journal: notes and photos")
    note = st.text_area("Notes", value=note_value or "", height=100, key=f"note_{stage}{pid}",
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

    blk("1 · The meat and the recipe")
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
        new_b = c1.selectbox("Blend", list(BLENDS), index=list(BLENDS).index(p["blend"]),
                             key=f"b{pid}", disabled=locked)
        new_w = c2.number_input("Meat weight after trimming [g]", min_value=1.0, step=1.0, format="%.0f",
                                value=float(p["green_weight_g"]), key=f"w{pid}", disabled=locked)
        new_e = c3.toggle("EcoCure #2", value=bool(p["ecocure"]), key=f"e{pid}", disabled=locked,
                          help="Adds 1 % EcoCure #2 and lowers the salt by half its weight, "
                               "so total salt stays at 3 %.")
        if not locked:
            changed = (new_b != p["blend"] or new_w != p["green_weight_g"] or new_e != bool(p["ecocure"]))

            def apply_recipe_change(con_, pid_):
                if new_b != p["blend"]:
                    db.change_blend(con_, pid_, new_b)
                db.update_spice_inputs(con_, pid_, green_weight_g=new_w, ecocure=new_e)

            if changed and not db.actuals_edited(con, pid):
                act(apply_recipe_change, pid, success="Plan recalculated")
            elif changed:
                st.warning("You have entered actual amounts or notes. Changing blend, weight or EcoCure "
                           "recalculates the plan and **replaces them with the new plan**.")
                c1, c2, _ = st.columns([1.6, 1, 2])
                if c1.button("Recalculate and reset", type="primary", key=f"rc_ok{pid}", width="stretch"):
                    act(apply_recipe_change, pid, success="Plan recalculated; actual amounts reset")
                if c2.button("Keep my amounts", key=f"rc_no{pid}", width="stretch"):
                    for k_ in (f"b{pid}", f"w{pid}", f"e{pid}"):
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
    ed_w = table(weighed, "%", "g", f"sw{pid}{ver}{p['ecocure']}{p['green_weight_g']}")
    ed_c = table(counted, "pcs / kg", "pcs", f"sc{pid}{ver}{p['green_weight_g']}") if counted else None

    acts = []
    for rows, ed, u in ((weighed, ed_w, "g"), (counted, ed_c, "pcs")):
        if ed is None:
            continue
        for l, (_, r) in zip(rows, ed.iterrows()):
            a = r[f"Actual [{u}]"]
            acts.append((l, None if pd.isna(a) else float(a), r["Note"] or None))
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
        if b1.button("Save", key=f"save_day0{pid}", width="stretch"):
            act(save_all, pid, success="Saved")
        if b2.button("Done: lock day 0 and start curing", type="primary", key=f"done_day0{pid}", width="stretch"):
            act(save_and_lock, pid, success="Day 0 locked. Curing has started.", goto="cure")
    else:
        unlock_panel("spice", p["spice_locked_at"], db.unlock_spice, "Day 0")


# --------------------------------------------------------------------------- #
# step 2: cure
# --------------------------------------------------------------------------- #

def step_cure():
    if not p["cure_start"] or not p["thickness_cm"]:
        st.info("Finish day 0 first: the cure time comes from the piece's thickness and the bag date.")
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
    if end_act:
        act_val, act_sub = f"{end_act:%d %b %Y}", "out of the bag"
        chip = (f'<span class="chip {"over" if diff > 0 else "ok"}">{diff:+d} vs plan</span>'
                if diff else '<span class="chip ok">as planned</span>')
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
                f'▲ planned end {planned:%d %b}</span>'
                + ('' if mark > 80 else f'<span style="right:0">{max(planned, run_to):%d %b}</span>') + '</div>')
    st.markdown('<span class="cureband"></span>', unsafe_allow_html=True)   # marker for tests
    band([("Cure started", f"{start:%d %b %Y}", "into the bag"),
          ("Planned end", f"{planned:%d %b %Y}", "start + planned days"),
          ("Actual end", act_val, act_sub),
          ("Calculator minimum", f"{mins:.1f} days", "before the 20 % margin"),
          ("Planned days", f"{days} days", "minimum + 20 %, rounded up"),
          ("Actual days", f"{actual_days} days{chip}",
           "longer is safe with equilibrium curing" if diff > 0 else "")], extra=timeline)

    blk("Unbag")
    with st.container(border=True):
        c1, c2 = st.columns([1, 2], vertical_alignment="bottom")
        c1.date_input("Taken out of the bag", value=d(p["cure_end_actual"]), format="DD/MM/YYYY",
                      key=k + "end", disabled=c_locked, help="Leave empty while the meat is still curing")
        c2.caption(f"Piece: {shape}, {thick:g} cm{' (estimate)' if p['thickness_estimated'] else ''}. "
                   "Change it on day 0.")
        if end_act and end_act < start:
            st.error("'Taken out of the bag' is before 'Into the bag'. Check the date.")

    old_note = "\n".join(x for x in (p["cure_method"], p["cure_note"]) if x)
    note = journal("cure", old_note, db.set_cure_note,
                   "Method and exceptions, e.g. flipped daily; missed a flip on day 12")

    def save_cure(con_, pid_):
        db.set_cure(con_, pid_, shape=shape, thickness_cm=thick, length_cm=p["length_cm"],
                    thickness_estimated=bool(p["thickness_estimated"]), start=start, end_actual=end_act,
                    method=None, note=note.strip() or None)

    def save_and_lock(con_, pid_):
        save_cure(con_, pid_)
        db.lock_cure(con_, pid_)

    blk("Done")
    if not closed:
        if not p["cure_locked_at"]:
            b1, b2, _ = st.columns([1.2, 2.2, 3])
            if b1.button("Save", key=f"save_cure{pid}", width="stretch",
                         disabled=(end_act.isoformat() if end_act else None) == p["cure_end_actual"]):
                act(save_cure, pid, success="Cure saved")
            if b2.button("Done: lock cure and start drying", type="primary", key=f"done_cure{pid}",
                         width="stretch", disabled=not end_act,
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
    """Weigh-in + optional chamber reading + optional photo, in one transaction."""
    try:
        with con:
            rid = db.add_reading(con, pid, r["day"], r["weight"], r["note"], confirmed=confirmed)
            if (r["temp"] is not None or r["rh"] is not None) and p["chamber_id"]:
                db.add_chamber_reading(con, p["chamber_id"], datetime.combine(
                    r["day"], db.now_local().time()).isoformat(timespec="minutes"), r["temp"], r["rh"])
            if r["photo"]:
                rel = storage.save_photo(pid, *r["photo"])   # raises ValueError if unreadable
                db.add_photo(con, pid, rel, r["day"], r["note"] or f"Weigh-in {r['weight']:.0f} g",
                             rid, stage="dry")
    except (db.Locked, ValueError) as e:
        st.error(str(e))
        return
    st.session_state["flash"] = f"Saved {r['weight']:.0f} g on {r['day']:%d %b}"
    st.rerun()


def step_dry_start():
    if not p["cure_locked_at"] and not closed:
        st.info("Lock the cure first. Drying then starts on the day the meat came out of the bag.")
    blk("Wrap, net and weigh")
    with st.form(f"drystart{pid}"):
        c1, c2, c3 = st.columns(3)
        ds = c1.date_input("Drying start", value=d(p["cure_end_actual"]) or db.today(), format="DD/MM/YYYY",
                           help="Defaults to the day the meat came out of the bag")
        sg = c2.number_input("Start weight incl. wrap + net [g]", min_value=1.0, value=None,
                             step=1.0, format="%.0f", placeholder="weigh it now",
                             help="Weigh the piece after wrapping and netting, before hanging it")
        tp = c3.number_input("Target loss [%]", min_value=1.0, max_value=70.0, value=35.0, step=1.0)
        names = [c["name"] for c in db.chambers(con)]
        c4, c5 = st.columns(2)
        ch_name = c4.selectbox("Drying chamber", names + ["+ New chamber"]) if names else "+ New chamber"
        new_ch = c5.text_input("New chamber name", value="Fridge drawer") if ch_name == "+ New chamber" else None
        with st.expander("Packaging weight (optional)"):
            tare = st.number_input("Packaging: wrap + net [g]", min_value=0.0, value=0.0, step=1.0, format="%.0f")
            tare_est = st.checkbox("Packaging weight is an estimate", value=True)
        if st.form_submit_button("Start drying", type="primary", disabled=closed or not p["cure_locked_at"]):
            if sg is None:
                st.error("Enter the start weight: weigh the piece with wrap and net.")
                return
            with con:
                ch = db.get_or_create_chamber(con, new_ch or ch_name)
            act(db.set_drying, pid, start=ds, start_gross_g=sg, chamber_id=ch, tare_g=tare,
                tare_estimated=tare_est, target_loss_pct=tp, success="Drying started")


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
            with st.expander("More: temperature, humidity, note, photo"):
                e1, e2 = st.columns(2)
                rt = e1.number_input("Chamber temperature [°C]", value=None, step=0.1, placeholder="optional",
                                     min_value=db.TEMP_RANGE[0], max_value=db.TEMP_RANGE[1])
                rh = e2.number_input("Chamber humidity [%]", value=None, step=1.0, placeholder="optional",
                                     min_value=db.RH_RANGE[0], max_value=db.RH_RANGE[1])
                rn = st.text_input("Note", placeholder="smell, firmness, mould")
                ph = st.file_uploader("Photo", type=storage.UPLOAD_TYPES)
            if submit:
                if rw is None:
                    st.error("Enter the weight.")
                else:
                    errors, warns = db.reading_problems(con, pid, rd, rw)
                    pending = dict(day=rd, weight=rw, temp=rt, rh=rh, note=rn or None,
                                   photo=(ph.name, ph.getvalue()) if ph is not None else None)
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
    m[1].metric("Target weight", f"{s['target_gross_g']:.0f} g", help=f"{p['target_loss_pct']:g} % loss on meat")
    m[2].metric("Weight lost", f"{s['loss_pct']:.1f} %")
    m[3].metric("Progress to target", f"{min(s['progress'], 1)*100:.0f} %")
    m[4].metric("Earliest finish", f"{eta.eta_date:%d %b}" if eta else "–",
                help=(f"Straight line through all weigh-ins ({eta.grams_per_day:.1f} g/day). "
                      "Drying slows down over time, so expect later." if eta else "Needs 2+ weigh-ins"))
    st.progress(min(max(s["progress"], 0.0), 1.0))

    # --- what happened ---------------------------------------------------------- #
    blk("What happened")
    rdf = pd.DataFrame([{"Date": pd.Timestamp(r["day"]), "Weight (g)": r["gross_g"]} for r in rows])
    line = alt.Chart(rdf).mark_line(point=True, color=RED).encode(
        x=alt.X("Date:T", title=None),
        y=alt.Y("Weight (g):Q", title="Weight incl. wrap + net [g]", scale=alt.Scale(
            zero=False, domain=[s["target_gross_g"] * 0.97, s["start_gross_g"] * 1.01])),
        tooltip=[alt.Tooltip("Date:T", format="%d %b %Y"), "Weight (g):Q"])
    target = alt.Chart(pd.DataFrame({"t": [s["target_gross_g"]]})).mark_rule(
        strokeDash=[6, 4], color=INK).encode(y=alt.Y("t:Q", title="Weight incl. wrap + net [g]"))
    left, right = st.columns([3, 2])
    left.altair_chart(alt.layer(line, target).properties(height=300), width="stretch")
    with right:
        tdf = pd.DataFrame([{
            "Date": d(r["day"]).strftime("%d %b"), "Day": (d(r["day"]) - d(p["dry_start"])).days,
            "Weight [g]": int(r["gross_g"]),
            "Lost [%]": round(calc.loss_pct(s["start_gross_g"], r["gross_g"], p["tare_g"]), 1),
            "Note": r["note"] or ""} for r in rows])
        st.dataframe(tdf, hide_index=True, width="stretch", height=300)
    cr = db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"]) if p["chamber_id"] else []
    if cr:
        with st.expander("Chamber temperature and humidity"):
            cdf = pd.DataFrame([{"Time": pd.Timestamp(c["ts"]), "°C": c["temp_c"], "RH %": c["rh_pct"]} for c in cr])
            st.line_chart(cdf.set_index("Time"), height=200)
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
        nt = c1.number_input("Target loss [%]", min_value=1.0, max_value=70.0, disabled=d_locked,
                             value=float(p["target_loss_pct"]), step=0.5, key=f"tgt{pid}")
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

        def note_and_lock(con_, pid_):
            db.set_dry_note(con_, pid_, note.strip())
            db.lock_dry(con_, pid_, de)
        if c2.button("Done: lock drying and finish", type="primary", key=f"dlk{pid}", width="stretch"):
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
               f"{calc.loss_pct(p['dry_start_gross_g'], final_g, p['tare_g']):.1f} % of the start weight"),
              ("Final ÷ raw meat" if p["dry_end"] else "Now ÷ raw meat", f"{100 * final_g / p['green_weight_g']:.0f} %",
               f"raw {p['green_weight_g']:.0f} g; includes wrap + net"),
              ("Cure", f"{cure_days} days" if cure_days is not None else "–", "in the bag"),
              ("Drying", f"{dry_days} days", "so far" if not p["dry_end"] else "wrapped and netted"),
              ("Total", f"{total_days} days", "from day 0")])
    else:
        st.info("The result appears here once drying has started.")

    if closed:
        st.success(f"Closed on {p['closed_at'][:10]}. This project is read-only.")
        if p["final_notes"]:
            blk("Final notes")
            st.write(p["final_notes"])
    else:
        blk("Close the batch")
        missing = db.close_problems(con, pid)
        if missing:
            st.info("Before this batch can be closed: " + "; ".join(missing) + ".")
        st.caption("Closing makes the project read-only. The PDF summary arrives in a later version.")
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
