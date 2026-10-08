"""Bresaola Tracker – Streamlit UI.

Run:  streamlit run app.py
"""
from __future__ import annotations

from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

from bresaola import __version__, calc, db, storage
from bresaola.blends import BLENDS
from bresaola.demo import seed_demo

st.set_page_config(page_title="Bresaola Tracker", page_icon="🥩", layout="wide")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def get_con():
    con = db.connect(storage.db_path())
    if storage.is_test_mode() and not db.projects(con):
        seed_demo(con)
    return con


def d(s):
    return date.fromisoformat(s) if s else None


def fmt_date(s):
    return d(s).strftime("%d %b %Y") if s else "–"


def act(fn, *a, success: str | None = None, **kw):
    """Run a db action, commit, report Locked/ValueError nicely, rerun on success."""
    try:
        with con:
            fn(con, *a, **kw)
    except (db.Locked, ValueError) as e:
        st.error(str(e))
        return False
    if success:
        st.session_state["flash"] = success
    st.rerun()


con = get_con()

# --------------------------------------------------------------------------- #
# sidebar: projects, new project, backup
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.title("Bresaola Tracker")
    st.caption(f"v{__version__}")

    projs = db.projects(con)
    labels = {p["id"]: f"{p['name']}{'  (closed)' if p['status'] == 'closed' else ''}" for p in projs}
    if projs:
        default = st.session_state.get("pid", projs[0]["id"])
        ids = list(labels)
        pid = st.radio("Projects", ids, index=ids.index(default) if default in ids else 0,
                       format_func=labels.get)
        st.session_state["pid"] = pid
    else:
        pid = None

    with st.expander("New project", expanded=not projs):
        with st.form("new_project", clear_on_submit=True):
            name = st.text_input("Name", placeholder="e.g. Valtellina Nov 2026")
            blend = st.selectbox("Spice blend", list(BLENDS))
            weight = st.number_input("Meat weight after trimming (g)", min_value=1.0, value=2000.0, step=1.0)
            eco = st.toggle("EcoCure #2 used")
            if st.form_submit_button("Create project", type="primary"):
                if not name.strip():
                    st.error("Give the project a name")
                else:
                    try:
                        with con:
                            new = db.create_project(con, name.strip(), blend, eco, weight)
                        st.session_state["pid"] = new
                        st.rerun()
                    except Exception as e:  # unique name etc.
                        st.error(f"Could not create: {e}")

    st.divider()
    st.subheader("Backup")
    st.download_button("Download backup", storage.make_backup(),
                       file_name=f"bresaola-backup-{date.today().isoformat()}.zip",
                       mime="application/zip", use_container_width=True)
    up = st.file_uploader("Restore from backup", type="zip", key="restore")
    if up is not None and st.button("Replace all data with this backup", type="secondary"):
        con.close()
        try:
            storage.restore_backup(up.getvalue())
            st.session_state.pop("pid", None)
            st.session_state["flash"] = "Backup restored"
        except ValueError as e:
            st.error(str(e))
        st.rerun()

# --------------------------------------------------------------------------- #
# header
# --------------------------------------------------------------------------- #

if storage.is_test_mode():
    st.warning("**Test mode.** Nothing here is stored permanently. Use *Download backup* in the "
               "sidebar to keep anything you enter.", icon="⚠️")

if msg := st.session_state.pop("flash", None):
    st.success(msg)

if pid is None:
    st.info("Create a project in the sidebar to start.")
    st.stop()

p = db.project(con, pid)
closed = p["status"] == "closed"
st.header(p["name"])
st.caption(f"{p['blend']} · EcoCure {'yes' if p['ecocure'] else 'no'} · "
           f"{p['green_weight_g']:.0f} g green weight · created {p['created_at'][:10]}"
           + (f" · **closed {p['closed_at'][:10]}**" if closed else ""))

tabs = st.tabs(["1 · Spice mix", "2 · Cure", "3 · Dry", "4 · Equalise", "Photos", "Close & history"])

# --------------------------------------------------------------------------- #
# 1. spice mix
# --------------------------------------------------------------------------- #

with tabs[0]:
    locked = bool(p["spice_locked_at"]) or closed
    lines = db.ingredient_lines(con, pid)

    if not locked:
        c1, c2, c3 = st.columns([2, 2, 1])
        new_w = c1.number_input("Meat weight after trimming (g)", min_value=1.0,
                                value=float(p["green_weight_g"]), step=1.0, key=f"w{pid}")
        new_b = c2.selectbox("Blend", list(BLENDS), index=list(BLENDS).index(p["blend"]), key=f"b{pid}")
        new_e = c3.toggle("EcoCure #2", value=bool(p["ecocure"]), key=f"e{pid}")
        if new_b != p["blend"]:
            act(db.change_blend, pid, new_b, success=f"Blend changed to {new_b}")
        elif new_w != p["green_weight_g"] or new_e != bool(p["ecocure"]):
            act(db.update_spice_inputs, pid, green_weight_g=new_w, ecocure=new_e,
                success="Plan recalculated (actual amounts reset to plan)")
        st.caption("Changing weight, blend or EcoCure recalculates the plan and resets actual amounts.")

    df = pd.DataFrame([{
        "Ingredient": l["name"],
        "Rate": f"{l['rate']*100:.3g} %" if l["unit"] == "pct" else f"{l['rate']:g} per kg",
        "Unit": "g" if l["unit"] == "pct" else "pcs",
        "Plan": round(l["planned"], 2),
        "Actual": None if l["actual"] is None else round(l["actual"], 2),
        "Note": l["note"] or "",
    } for l in lines])

    edited = st.data_editor(
        df, hide_index=True, use_container_width=True, disabled=locked,
        column_config={c: st.column_config.Column(disabled=True) for c in ["Ingredient", "Rate", "Unit", "Plan"]},
        key=f"spice{pid}{p['spice_locked_at']}")

    plan_g = sum(l["planned"] for l in lines if l["unit"] == "pct")
    act_g = sum(r["Actual"] or 0 for _, r in edited.iterrows() if r["Unit"] == "g")
    m1, m2 = st.columns(2)
    m1.metric("Total planned (g)", f"{plan_g:.1f}")
    m2.metric("Total actual (g)", f"{act_g:.1f}", delta=f"{act_g - plan_g:+.1f} g", delta_color="off")

    if closed:
        pass
    elif not p["spice_locked_at"]:
        b1, b2 = st.columns([1, 4])
        if b1.button("Save actual amounts"):
            with con:
                for i, row in edited.iterrows():
                    a = row["Actual"]
                    db.set_actual(con, pid, lines[i]["position"],
                                  None if pd.isna(a) else float(a), row["Note"] or None)
            st.session_state["flash"] = "Saved"
            st.rerun()
        if b2.button("Done: lock spice mix", type="primary"):
            with con:
                for i, row in edited.iterrows():
                    a = row["Actual"]
                    db.set_actual(con, pid, lines[i]["position"],
                                  None if pd.isna(a) else float(a), row["Note"] or None)
                db.lock_spice(con, pid)
            st.session_state["flash"] = "Spice mix locked"
            st.rerun()
    else:
        st.info(f"Locked {p['spice_locked_at'].replace('T', ' ')}.")
        with st.expander("Unlock to edit"):
            reason = st.text_input("Reason (saved in history)", key=f"unl{pid}")
            if st.button("Unlock spice mix", disabled=not reason.strip()):
                act(db.unlock_spice, pid, reason.strip(), success="Unlocked")

# --------------------------------------------------------------------------- #
# 2. cure
# --------------------------------------------------------------------------- #

with tabs[1]:
    with st.form(f"cure{pid}"):
        c1, c2, c3 = st.columns(3)
        shape = c1.radio("Shape", ["tubular", "flat"], horizontal=True,
                         index=0 if (p["shape"] or "tubular") == "tubular" else 1,
                         help="Tubular: eye of round, tenderloin. Flat: brisket.")
        thick = c2.number_input("Narrowest dimension across the thickest part (cm)", min_value=0.5,
                                value=float(p["thickness_cm"] or 8.0), step=0.5)
        length = c3.number_input("Length (cm)", min_value=0.0, value=float(p["length_cm"] or 0.0), step=0.5,
                                 help="Optional. Used to check the dimensions against the weight.")
        est = st.checkbox("Thickness is an estimate", value=bool(p["thickness_estimated"]))
        c4, c5 = st.columns(2)
        start = c4.date_input("Cure start", value=d(p["cure_start"]) or date.today(), format="DD/MM/YYYY")
        has_end = c5.checkbox("Taken out of the bag", value=bool(p["cure_end_actual"]))
        end_act = c5.date_input("Actual end", value=d(p["cure_end_actual"]) or date.today(),
                                format="DD/MM/YYYY", disabled=False)
        method = st.text_input("Method", value=p["cure_method"] or
                               "Equilibrium dry cure, vacuum-sealed, fridge, flipped and massaged daily")
        note = st.text_area("Notes and exceptions", value=p["cure_note"] or "", height=80)
        if st.form_submit_button("Save cure", type="primary", disabled=closed):
            act(db.set_cure, pid, shape=shape, thickness_cm=thick, length_cm=length or None,
                thickness_estimated=est, start=start, end_actual=end_act if has_end else None,
                method=method, note=note or None, success="Cure saved")

    mins = calc.cure_days_minimum(thick, shape)
    days = calc.cure_days(thick, shape)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Calculator minimum", f"{mins:.1f} days")
    k2.metric("Cure time (+20 %)", f"{days} days")
    k3.metric("Planned end", fmt_date(p["cure_end_planned"]) if p["cure_start"] else "–")
    if p["cure_end_actual"] and p["cure_start"]:
        actual_days = (d(p["cure_end_actual"]) - d(p["cure_start"])).days
        k4.metric("Actual", f"{actual_days} days", delta=f"{actual_days - days:+d} vs plan", delta_color="off")
    elif p["cure_start"]:
        left = (d(p["cure_end_planned"]) - date.today()).days
        k4.metric("Remaining", f"{max(left, 0)} days")

    if shape == "tubular" and length:
        implied_g = 1.05 * 3.1416 * (thick / 2) ** 2 * length
        ratio = implied_g / p["green_weight_g"]
        if not 0.6 < ratio < 1.6:
            st.warning(f"Dimensions don't match the weight: a {thick:g} × {length:g} cm cylinder weighs about "
                       f"{implied_g:.0f} g, the piece weighs {p['green_weight_g']:.0f} g. Check the measurement.")
    st.caption("Formula: genuineideas.com equilibrium brine calculator, 1.25 × (thickness in inches)² days "
               "for flat, half for tubular; +20 % to cure to the centre; rounded up. Fridge 1–3 °C.")

# --------------------------------------------------------------------------- #
# 3. dry
# --------------------------------------------------------------------------- #

with tabs[2]:
    if not p["dry_start"]:
        st.subheader("Start drying")
        with st.form(f"drystart{pid}"):
            c1, c2, c3 = st.columns(3)
            ds = c1.date_input("Drying start", value=d(p["cure_end_actual"]) or date.today(), format="DD/MM/YYYY")
            sg = c2.number_input("Start weight incl. wrap + net (g)", min_value=1.0,
                                 value=float(p["green_weight_g"]), step=1.0)
            tp = c3.number_input("Target loss (%)", min_value=1.0, max_value=70.0, value=35.0, step=1.0)
            c4, c5 = st.columns(2)
            tare = c4.number_input("Packaging weight: wrap + net (g)", min_value=0.0, value=0.0, step=1.0)
            tare_est = c5.checkbox("Packaging weight is an estimate", value=True)
            names = [c["name"] for c in db.chambers(con)]
            ch_name = st.selectbox("Drying chamber", names + ["+ New chamber"]) if names else "+ New chamber"
            new_ch = st.text_input("New chamber name", value="Fridge drawer") if ch_name == "+ New chamber" else None
            if st.form_submit_button("Start drying", type="primary", disabled=closed):
                with con:
                    ch = db.get_or_create_chamber(con, new_ch or ch_name)
                act(db.set_drying, pid, start=ds, start_gross_g=sg, chamber_id=ch, tare_g=tare,
                    tare_estimated=tare_est, target_loss_pct=tp, success="Drying started")
    else:
        s = db.drying_status(con, pid)
        eta = s["eta"]
        m = st.columns(5)
        m[0].metric("Latest weight", f"{s['latest_gross_g']:.0f} g", help=f"on {s['latest_day']:%d %b %Y}")
        m[1].metric("Target weight", f"{s['target_gross_g']:.0f} g", help=f"{p['target_loss_pct']:g} % loss on meat")
        m[2].metric("Weight lost", f"{s['loss_pct']:.1f} %")
        m[3].metric("Progress to target", f"{min(s['progress'], 1)*100:.0f} %")
        m[4].metric("Earliest finish", f"{eta.eta_date:%d %b}" if eta else "–",
                    help=(f"Straight line through all weigh-ins ({eta.grams_per_day:.1f} g/day). "
                          "Drying slows down over time, so expect later." if eta else "Needs 2+ weigh-ins"))
        st.progress(min(max(s["progress"], 0.0), 1.0))
        if s["progress"] >= 1 and not p["dry_end"]:
            st.success("Target weight reached.")

        # chart
        rows = db.reading_rows(con, pid)
        rdf = pd.DataFrame([{"Date": pd.Timestamp(r["day"]), "Weight (g)": r["gross_g"]} for r in rows])
        base = alt.Chart(rdf).encode(x=alt.X("Date:T", title=None))
        line = base.mark_line(point=True).encode(
            y=alt.Y("Weight (g):Q", title="Weight incl. wrap + net (g)", scale=alt.Scale(zero=False,
                    domain=[s["target_gross_g"] * 0.97, s["start_gross_g"] * 1.01])),
            tooltip=[alt.Tooltip("Date:T", format="%d %b %Y"), "Weight (g):Q"])
        target = alt.Chart(pd.DataFrame({"t": [s["target_gross_g"]]})).mark_rule(
            strokeDash=[6, 4], color="#b5543c").encode(y=alt.Y("t:Q", title="Weight incl. wrap + net (g)"))
        layers = [line, target]
        if p["chamber_id"]:
            cr = db.chamber_readings(con, p["chamber_id"], p["dry_start"], p["dry_end"])
            if cr:
                cdf = pd.DataFrame([{"Time": pd.Timestamp(c["ts"]), "°C": c["temp_c"], "RH %": c["rh_pct"]} for c in cr])
        st.altair_chart(alt.layer(*layers).properties(height=320), use_container_width=True)
        if p["chamber_id"] and cr:
            with st.expander("Chamber temperature and humidity"):
                st.line_chart(cdf.set_index("Time"), height=200)

        left, right = st.columns([3, 2])
        with left:
            st.subheader("Add weigh-in")
            with st.form(f"reading{pid}", clear_on_submit=True):
                c1, c2 = st.columns(2)
                rd = c1.date_input("Date", value=date.today(), format="DD/MM/YYYY")
                rw = c2.number_input("Weight incl. wrap + net (g)", min_value=1.0,
                                     value=float(s["latest_gross_g"]), step=1.0)
                c3, c4 = st.columns(2)
                rt = c3.number_input("Chamber temp (°C)", value=None, step=0.1, placeholder="optional")
                rh = c4.number_input("Chamber humidity (%)", value=None, step=1.0, placeholder="optional")
                rn = st.text_input("Note", placeholder="optional: smell, firmness, mould ...")
                ph = st.file_uploader("Photo", type=["jpg", "jpeg", "png", "webp"])
                if st.form_submit_button("Save weigh-in", type="primary", disabled=closed):
                    try:
                        with con:
                            rid = db.add_reading(con, pid, rd, rw, rn or None)
                            if (rt is not None or rh is not None) and p["chamber_id"]:
                                db.add_chamber_reading(con, p["chamber_id"],
                                                       datetime.combine(rd, datetime.now().time()).isoformat(timespec="minutes"),
                                                       rt, rh)
                            if ph is not None:
                                rel = storage.save_photo(pid, ph.name, ph.getvalue())
                                rid = con.execute("SELECT id FROM reading WHERE project_id=? AND day=?",
                                                  (pid, rd.isoformat())).fetchone()["id"]
                                db.add_photo(con, pid, rel, rd, rn or f"Weigh-in {rw:.0f} g", rid)
                        st.session_state["flash"] = f"Saved {rw:.0f} g on {rd:%d %b}"
                        st.rerun()
                    except db.Locked as e:
                        st.error(str(e))
        with right:
            st.subheader("Weigh-ins")
            tdf = pd.DataFrame([{
                "Date": d(r["day"]).strftime("%d %b"), "Day": (d(r["day"]) - d(p["dry_start"])).days,
                "Weight (g)": int(r["gross_g"]),
                "Lost (%)": round(calc.loss_pct(s["start_gross_g"], r["gross_g"], p["tare_g"]), 1),
                "Note": r["note"] or ""} for r in rows])
            st.dataframe(tdf, hide_index=True, use_container_width=True, height=280)
            if not closed and len(rows) > 1:
                with st.expander("Delete a weigh-in"):
                    choice = st.selectbox("Weigh-in", [r["day"] for r in rows[1:]], format_func=fmt_date)
                    if st.button("Delete"):
                        act(db.delete_reading, pid, choice, success="Deleted")

        with st.expander("Settings: target, packaging, end of drying"):
            c1, c2 = st.columns(2)
            nt = c1.number_input("Target loss (%)", min_value=1.0, max_value=70.0,
                                 value=float(p["target_loss_pct"]), step=0.5, key=f"tgt{pid}")
            why = c2.text_input("Reason for change", key=f"why{pid}")
            if st.button("Change target", disabled=closed or nt == p["target_loss_pct"]):
                act(db.change_target, pid, nt, why, success="Target changed")
            st.caption(f"Packaging weight {p['tare_g']:g} g"
                       + (" (estimate)" if p["tare_estimated"] else "")
                       + (f" · {p['dry_note']}" if p["dry_note"] else ""))
            de = st.date_input("Drying ended", value=d(p["dry_end"]) or date.today(),
                               format="DD/MM/YYYY", key=f"de{pid}")
            if st.button("Mark drying finished", disabled=closed):
                act(db.end_drying, pid, de, success="Drying finished")

# --------------------------------------------------------------------------- #
# 4. equalise
# --------------------------------------------------------------------------- #

with tabs[3]:
    st.caption("Optional. Vacuum-seal after reaching the target weight and rest in the fridge so moisture "
               "evens out between the surface and the centre.")
    with st.form(f"eq{pid}"):
        c1, c2, c3 = st.columns(3)
        use_start = c1.checkbox("Started", value=bool(p["equalise_start"]))
        es = c1.date_input("Start", value=d(p["equalise_start"]) or d(p["dry_end"]) or date.today(), format="DD/MM/YYYY")
        use_end = c2.checkbox("Finished", value=bool(p["equalise_end"]))
        ee = c2.date_input("End", value=d(p["equalise_end"]) or date.today(), format="DD/MM/YYYY")
        ew = c3.number_input("Weight at end (g)", min_value=0.0, value=float(p["equalise_end_gross_g"] or 0), step=1.0)
        en = st.text_area("Notes", value=p["equalise_note"] or "", height=80)
        if st.form_submit_button("Save", type="primary", disabled=closed):
            act(db.set_equalise, pid, start=es if use_start else None, end=ee if use_end else None,
                end_gross_g=ew or None, note=en or None, success="Saved")
    if p["equalise_start"]:
        end = d(p["equalise_end"]) or date.today()
        st.metric("Days equalising", (end - d(p["equalise_start"])).days)

# --------------------------------------------------------------------------- #
# photos
# --------------------------------------------------------------------------- #

with tabs[4]:
    with st.form(f"photo{pid}", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1, 2])
        files = c1.file_uploader("Add photos", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
        pd_ = c2.date_input("Taken on", value=date.today(), format="DD/MM/YYYY")
        cap = c3.text_input("Caption")
        if st.form_submit_button("Upload", disabled=closed) and files:
            with con:
                for f in files:
                    db.add_photo(con, pid, storage.save_photo(pid, f.name, f.getvalue()), pd_, cap or None)
            st.session_state["flash"] = f"{len(files)} photo(s) added"
            st.rerun()
    ph = db.photos(con, pid)
    if not ph:
        st.info("No photos yet. Add one here or with a weigh-in.")
    cols = st.columns(4)
    for i, r in enumerate(ph):
        f = storage.photo_file(r["path"])
        with cols[i % 4]:
            if f.exists():
                st.image(str(f), use_container_width=True)
            else:
                st.warning("File missing")
            st.caption(f"{fmt_date(r['taken_at'][:10])} · {r['caption'] or ''}")

# --------------------------------------------------------------------------- #
# close & history
# --------------------------------------------------------------------------- #

with tabs[5]:
    if closed:
        st.success(f"Closed on {p['closed_at'][:10]}. This project is read-only.")
        if p["final_notes"]:
            st.write(p["final_notes"])
    else:
        st.subheader("Close project")
        st.caption("Closing makes the project read-only. The PDF summary arrives in a later version.")
        with st.form(f"close{pid}"):
            fn = st.text_area("Final notes: texture, taste, what to change next time", height=120)
            sure = st.checkbox("I understand the project becomes read-only")
            if st.form_submit_button("Close project", type="primary"):
                if not sure:
                    st.error("Tick the box to confirm")
                else:
                    act(db.close_project, pid, fn, success="Project closed")
    st.subheader("History")
    ev = db.events(con, pid)
    st.dataframe(pd.DataFrame([{"When": e["ts"].replace("T", " "), "What": e["kind"].replace("_", " "),
                                "Detail": e["detail"] or ""} for e in ev]),
                 hide_index=True, use_container_width=True)
