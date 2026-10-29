"""Shared test helpers."""


def pick_project(at, pid):
    """Select project `pid` in the sidebar: radio for active projects, dropdown for closed ones (v0.4.18)."""
    for r in at.sidebar.radio:
        if r.label == "Active projects" and r.format_func(pid) in r.options:
            return r.set_value(pid)
    return next(s for s in at.sidebar.selectbox if s.label == "Closed projects").set_value(pid)


def all_layers(spec):
    """Every layer / single view in a Vega-Lite spec, through vconcat, hconcat and layer (v0.4.21)."""
    out = []
    for k in ("layer", "vconcat", "hconcat", "concat"):
        for sub in spec.get(k, []):
            out += all_layers(sub) if any(j in sub for j in ("layer", "vconcat", "hconcat", "concat")) else [sub]
    return out
