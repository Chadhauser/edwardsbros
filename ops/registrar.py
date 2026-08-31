#!/usr/bin/env python3
"""The Registrar (S4) -- obligations lookahead for the Estate Monday Digest.

Three sources, all free:
  1. Companies House public API (CS01 + accounts due dates from the CRNs).
  2. A fixed obligations table maintained in this file.
  3. RDAP domain expiry lookups (best effort -- some registries do not publish).

Never crashes: every lookup is guarded and failures become warning lines.
"""

import datetime as dt
import os
import time

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

TIMEOUT = 25
HEADERS = {"User-Agent": "EdwardsBros-Registrar/1.0"}
LOOKAHEAD_DAYS = 60

COMPANIES = [
    ("00598511", "Edwards Bros (Spaldwick) Ltd"),
    ("16943160", "Insight Professional Partners Ltd"),
]

# Fixed obligations. date=None means "date not yet supplied" -- these are
# surfaced as an explicit gap rather than silently omitted.
# approx=True renders the date as approximate.
FIXED = [
    # (name, date, approx)
    ("IASME course", dt.date(2026, 10, 20), False),
    ("Cyber Essentials assessor renewal", dt.date(2027, 8, 1), True),
    ("CIMA CPD declaration", None, False),
    ("ICO registration ZA900683 renewal", None, False),
    ("FIBA membership FIB42279 renewal", None, False),
    ("Professional indemnity renewal", None, False),
    ("VAT quarter end -- Edwards Bros (Spaldwick) Ltd", None, False),
    ("VAT quarter end -- Insight Professional Partners Ltd", None, False),
]

DOMAINS = [
    "edwardsbros.co.uk",
    "granton.finance",
    "passcyber.co.uk",
    "glebeassurance.co.uk",
    "sheetmtd.co.uk",
    "insightprofessionalpartners.com",
    "financeclearly.com",
    "vigilledger.com",
    "theedgeletter.com",
]

CH_BASE = "https://api.company-information.service.gov.uk/company/"
RDAP_BASE = "https://rdap.org/domain/"


def _parse(d):
    try:
        return dt.date.fromisoformat(str(d)[:10])
    except Exception:
        return None


# ------------------------------------------------------------ Companies House

def companies_house_items():
    """Return (items, warnings). items are (date, label) tuples."""
    items, warns = [], []
    key = os.environ.get("CH_API_KEY")
    if not key:
        return items, ["Companies House: CH_API_KEY secret not set -- filing dates unavailable."]
    if requests is None:
        return items, ["Companies House: requests unavailable."]
    for crn, name in COMPANIES:
        try:
            r = requests.get(CH_BASE + crn, auth=(key, ""), timeout=TIMEOUT, headers=HEADERS)
            if r.status_code == 401:
                warns.append("Companies House: key rejected (401) -- check CH_API_KEY is a live REST key.")
                break
            if r.status_code >= 400:
                warns.append("Companies House %s: HTTP %s." % (crn, r.status_code))
                continue
            data = r.json()
            cs = (data.get("confirmation_statement") or {})
            acc = (data.get("accounts") or {})
            nxt = (acc.get("next_accounts") or {})
            for due, label in (
                (_parse(cs.get("next_due")), "CS01 confirmation statement"),
                (_parse(nxt.get("due_on") or acc.get("next_due")), "Annual accounts"),
            ):
                if due:
                    items.append((due, "%s -- %s" % (label, name)))
        except Exception as e:
            warns.append("Companies House %s: %s." % (crn, type(e).__name__))
    return items, warns


# -------------------------------------------------------------------- domains

def domain_items():
    items, warns, unknown = [], [], []
    if requests is None:
        return items, ["Domains: requests unavailable."], unknown
    for domain in DOMAINS:
        try:
            r = requests.get(RDAP_BASE + domain, timeout=TIMEOUT, headers=HEADERS,
                             allow_redirects=True)
            if r.status_code >= 400:
                unknown.append(domain)
                continue
            expiry = None
            for ev in (r.json().get("events") or []):
                if (ev.get("eventAction") or "").lower() == "expiration":
                    expiry = _parse(ev.get("eventDate"))
                    break
            if expiry:
                items.append((expiry, "Domain expiry -- %s" % domain))
            else:
                unknown.append(domain)
        except Exception:
            unknown.append(domain)
        time.sleep(0.5)
    return items, warns, unknown


# --------------------------------------------------------------------- output

def section_registrar():
    today = dt.date.today()
    horizon = today + dt.timedelta(days=LOOKAHEAD_DAYS)
    lines = ["## Registrar -- %d-day lookahead" % LOOKAHEAD_DAYS, ""]

    items, warns = companies_house_items()
    dom_items, dom_warns, dom_unknown = domain_items()
    items += dom_items
    warns += dom_warns

    missing = []
    for name, due, approx in FIXED:
        if due is None:
            missing.append(name)
        else:
            items.append((due, name + (" (approx)" if approx else "")))

    due_soon = sorted([i for i in items if i[0] <= horizon])
    later = sorted([i for i in items if i[0] > horizon])

    if not due_soon:
        lines.append("Nothing due in the next %d days." % LOOKAHEAD_DAYS)
    else:
        for due, label in due_soon:
            days = (due - today).days
            if days < 0:
                lines.append("- **%s -- OVERDUE by %d days** (was due %s)." % (label, -days, due))
            elif days <= 14:
                lines.append("- **%s -- %s (%d days)**" % (label, due, days))
            else:
                lines.append("- %s -- %s (%d days)" % (label, due, days))
    lines.append("")

    if later:
        lines.append("<details><summary>Beyond %d days (%d items)</summary>"
                     % (LOOKAHEAD_DAYS, len(later)))
        lines.append("")
        for due, label in later:
            lines.append("- %s -- %s" % (label, due))
        lines.append("")
        lines.append("</details>")
        lines.append("")

    if missing:
        lines.append("**Dates not yet set** -- these are tracked but have no date, so they "
                     "cannot be counted down. Add them in `ops/registrar.py`:")
        for name in missing:
            lines.append("- %s" % name)
        lines.append("")

    if dom_unknown:
        lines.append("_Domain expiry not published by the registry for: %s._"
                     % ", ".join(dom_unknown))
        lines.append("")

    for w in warns:
        lines.append("> WARNING: %s" % w)
    if warns:
        lines.append("")

    return lines
