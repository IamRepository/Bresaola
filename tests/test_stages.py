from bresaola.stages import stage_states


def P(**kw):
    base = dict(status="active", spice_locked_at=None, cure_start=None, cure_locked_at=None,
                dry_start=None, dry_locked_at=None, equalise_start=None, equalise_end=None,
                equalise_locked_at=None)
    base.update(kw)
    return base


def test_new_project_is_on_spice_mix():
    assert stage_states(P()) == ["current", "todo", "todo", "optional"]


def test_palermo_today_is_drying():
    p = P(spice_locked_at="x", cure_start="a", cure_locked_at="b", dry_start="c")
    assert stage_states(p) == ["done", "done", "current", "optional"]


def test_after_drying_equalise_stays_optional_until_started():
    p = P(spice_locked_at="x", cure_locked_at="b", dry_locked_at="d")
    assert stage_states(p) == ["done", "done", "done", "optional"]
    assert stage_states({**p, "equalise_start": "e"})[3] == "current"


def test_closed_has_no_current_stage():
    assert "current" not in stage_states(P(status="closed", spice_locked_at="x"))
