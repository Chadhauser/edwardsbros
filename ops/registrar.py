#!/usr/bin/env python3
"""The Registrar (S4) -- obligations lookahead for the Estate Monday Digest.

Four sources, all free:
  1. Companies House public API (CS01 + accounts due dates from the CRNs).
  2. Recurring rules -- annual renewals and VAT quarters, computed forward
     from today so they never go stale.
  3. One-off fixed dates.
  4. RDAP domain expiry lookups, retried; a miss means the lookup failed or
     the registry does not publish -- the two are not distinguished.

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

# ---------------------------------------------------------------- VAT quarters
# months = the months in which a VAT quarter ENDS.
# not_before = first quarter end that applies (for a long first period).
# Filing and payment are due one calendar month and seven days after the
# quarter end, so both dates are surfaced.
VAT_SCHEDULES = [
    # (entity, quarter-end months, not_before)
    ("Edwards Bros (Spaldwick) Ltd", (1, 4, 7, 10), None),
    ("Insight Professional Partners Ltd", (3, 6, 9, 12), dt.date(2026, 12, 31)),
]

# ------------------------------------------------------------ annual renewals
# (name, month, day, approx) -- recurs every year, next occurrence is computed.
ANNUAL = [
    ("Professional indemnity renewal", 1, 31, False),
    ("ICO registration ZA900683 renewal", 6, 1, True),
    ("FIBA membership FIB42279 renewal", 7, 1, True),
]

# ------------------------------------------------------------- one-off dates
# date=None means "not yet supplied" -- surfaced as an explicit gap.
FIXED = [
    # (name, date, approx)
    ("IASME course", dt.date(2026, 10, 20), False),
    ("Cyber Essentials assessor renewal", dt.date(2027, 8, 1), True),
    ("CIMA CPD declaration", None, False),
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


def _end_of_month(year, month):
    if month == 12:
        return dt.date(year, 12, 31)
    return dt.date(year, month + 1, 1) - dt.timedelta(days=1)


def _add_month(d):
    """Same day next month, clamped to the month end."""
    year = d.year + (1 if d.month == 12 else 0)
    month = 1 if d.month == 12 else d.month + 1
    last = _end_of_month(year, month).day
    return dt.date(year, month, min(d.day, last))


def _next_annual(today, month, day):
    """Next occurrence of month/day on or after today."""
    for year in (today.year, today.year + 1):
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            candidate = _end_of_month(year, month)
        if candidate >= today:
            return candidate
    return None


def vat_items(today):
    """Next VAT quarter end and its filing deadline for each entity."""
    items = []
    for entity, months, not_before in VAT_SCHEDULES:
        candidates = []
        for year in (today.year, today.year + 1, today.year + 2):
            for month in months:
                end = _end_of_month(year, month)
                if end < today:
                    continue
                if not_before and end < not_before:
                    continue
                candidates.append(end)
        if not candidates:
            continue
        quarter_end = min(candidates)
        deadline = _add_month(quarter_end) + dt.timedelta(days=7)
        items.append((quarter_end, "VAT quarter end -- %s" % entity))
        items.append((deadline, "VAT return and payment due -- %s" % entity))
    return items


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

def _rdap_expiry(domain, attempts=3):
    """Return (expiry_date, note). note is None on success."""
    last = None
    for i in range(attempts):
        try:
            r = requests.get(RDAP_BASE + domain, timeout=TIMEOUT, headers=HEADERS,
                             allow_redirects=True)
            if r.status_code == 404:
                return None, "no RDAP record"
            if r.status_code >= 400:
                last = "HTTP %s" % r.status_code
            else:
                for ev in (r.json().get("events") or []):
                    if (ev.get("eventAction") or "").lower() == "expiration":
                        return _parse(ev.get("eventDate")), None
                return None, "registry publishes no expiry date"
        except Exception as e:
            last = type(e).__name__
        if i < attempts - 1:
            time.sleep(3)
    return None, "lookup failed (%s)" % last


def domain_items():
    items, warns, unknown = [], [], []
    if requests is None:
        return items, ["Domains: requests unavailable."], unknown
    for domain in DOMAINS:
        expiry, note = _rdap_expiry(domain)
        if expiry:
            items.append((expiry, "Domain expiry -- %s" % domain))
        else:
            unknown.append("%s (%s)" % (domain, note))
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

    try:
        items += vat_items(today)
    except Exception as e:
        warns.append("VAT schedule calculation failed (%s)." % type(e).__name__)

    for name, month, day, approx in ANNUAL:
        due = _next_annual(today, month, day)
        if due:
            items.append((due, name + (" (approx)" if approx else "")))

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
        lines.append("_No expiry date for: %s._" % "; ".join(dom_unknown))
        lines.append("")

    for w in warns:
        lines.append("> WARNING: %s" % w)
    if warns:
        lines.append("")

    return lines
