#!/usr/bin/env python3
"""Build Board -- the automation programme reporting on itself.

Edit STAGES as stages move. Status is deliberately hand-maintained: it is a
statement of intent, not something the machine can infer about itself.

Status values: not started | built | live | verified | spec only
"""

# (id, name, status, next gate, blocker)
STAGES = [
    ("S1", "Estate Monday Digest", "verified",
     "Runs unattended Mon 06:00 UTC", ""),
    ("S2", "Tender radar tuning", "live",
     "Review out-of-area matches, then narrow or widen", ""),
    ("S3", "The Chaser", "not started",
     "Spec agreed, then Apps Script paste", "Peter: seed list of what is owed + one paste"),
    ("S4", "The Registrar", "live",
     "Fill remaining dates", "Peter: CIMA CPD date; exact days for ICO and FIBA"),
    ("S5a", "Drive restructure", "not started",
     "Build tree, then propose move list", "Peter: approve the move list before anything moves"),
    ("S5", "Filing Clerk", "not started",
     "Depends on S5a", "S5a complete + one Apps Script paste"),
    ("S6", "Onboarding Clerk", "not started",
     "Derive entity variants from the base template",
     "Peter: decision on registered office shown on letters"),
    ("S7", "Owner Radar", "not started",
     "Build monthly action; CH key already in place", ""),
    ("S8", "App-store crawler", "not started",
     "Build after S7", ""),
    ("E-L", "Compliance e-learning", "spec only",
     "Own build session", "Chassis decision pending Training Tracker reply"),
]


def section_build_board():
    lines = ["## Build Board", ""]
    lines.append("| Stage | Status | Next gate | Blocked on |")
    lines.append("| --- | --- | --- | --- |")
    for sid, name, status, gate, blocker in STAGES:
        flag = "**%s**" % status if blocker else status
        lines.append("| %s %s | %s | %s | %s |"
                     % (sid, name, flag, gate, blocker or "--"))
    lines.append("")
    blocked = [s for s in STAGES if s[4]]
    if blocked:
        lines.append("%d stage(s) waiting on an input." % len(blocked))
        lines.append("")
    return lines
