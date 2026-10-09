"""Where a batch is: status of each stage, for the stage track in the UI."""


def stage_states(p) -> list[str]:
    """done / current / todo / optional for the four stages, in order."""
    done = [bool(p["spice_locked_at"]), bool(p["cure_locked_at"]), bool(p["dry_locked_at"]),
            bool(p["equalise_locked_at"])]
    started = [True, bool(p["cure_start"]), bool(p["dry_start"]), bool(p["equalise_start"])]
    states, current_found = [], p["status"] == "closed"
    for i, (dn, st_) in enumerate(zip(done, started)):
        if dn:
            states.append("done")
        elif not current_found and (st_ or i == 0 or done[i - 1]):
            states.append("current"); current_found = True
        else:
            states.append("optional" if i == 3 else "todo")
    if states[3] == "current" and not p["equalise_start"]:
        states[3] = "optional"          # equalise is never forced as the next step
    return states
