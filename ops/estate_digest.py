#!/usr/bin/env python3
"""Estate Monday Digest (S1).

Deterministic core: free public endpoints only. No AI, no paid APIs, no local
dependencies -- runs entirely on GitHub Actions.

Design rule: this script must never crash. Every section is guarded; any
failure becomes a warning line in the digest instead of a dead system.

Output: a GitHub Issue on this repository.
"""

import datetime as dt
import json
import os
import sys
import xml.etree.ElementTree as ET

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

TIMEOUT = 25
HEADERS = {"User-Agent": "EdwardsBros-EstateDigest/1.0"}

# ---------------------------------------------------------------- (a) sites

SITES = [
    "https://www.edwardsbros.co.uk",
    "https://granton.finance",
    "https://passcyber.co.uk",
    "https://glebeassurance.co.uk",
    "https://sheetmtd.co.uk",
    "https://insightprofessionalpartners.com",
    "https://financeclearly.com",
    "https://www.vigilledger.com",
    "https://theedgeletter.com",
]

# -------------------------------------------------------------- (b) tenders

# Keyword groups -- an item must match at least one of these.
KEYWORDS = [
    "internal audit",
    "parish council",
    "town council",
    "annual governance",
    "grounds maintenance",
    "grass cutting",
    "cyber essentials",
    "iasme",
]

# Area terms -- counties plus their main towns.
AREAS = [
    "cambridgeshire", "cambridge", "huntingdon", "st neots", "st ives",
    "ely", "march", "wisbech", "sawtry", "ramsey",
    "northamptonshire", "northampton", "kettering", "corby",
    "wellingborough", "daventry", "rushden", "thrapston", "oundle",
    "rutland", "oakham", "uppingham",
    "bedfordshire", "bedford", "luton", "dunstable", "biggleswade",
    "milton keynes",
    "peterborough",
    "leicestershire", "leicester", "loughborough", "melton",
    "hinckley", "coalville", "market harborough",
]

OCDS_URL = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"

# ----------------------------------------------------------- (c) reminders

REMINDERS = [
    ("Disavow file refresh", dt.date(2026, 11, 1)),
    ("Ahrefs cancellation check", None),  # standing monthly check
]


def _get(url, **kw):
    if requests is None:
        raise RuntimeError("requests unavailable")
    return requests.get(url, timeout=TIMEOUT, headers=HEADERS, **kw)


# ------------------------------------------------------------------ section a

def section_sites():
    lines = ["## Sites", ""]
    lines.append("| Site | Status | ms | Sitemap | URLs |")
    lines.append("| --- | --- | --- | --- | --- |")
    for base in SITES:
        host = base.replace("https://", "")
        status, ms = "?", "?"
        sm, count = "?", "?"
        try:
            r = _get(base, allow_redirects=True)
            status = str(r.status_code)
            ms = str(int(r.elapsed.total_seconds() * 1000))
            if r.status_code >= 400:
                status = "DOWN " + status
        except Exception as e:
            status = "DOWN"
            ms = type(e).__name__
        try:
            r = _get(base.rstrip("/") + "/sitemap.xml", allow_redirects=True)
            if r.status_code >= 400:
                sm, count = "missing (%s)" % r.status_code, "0"
            else:
                root = ET.fromstring(r.content)
                locs = [e for e in root.iter() if e.tag.endswith("}loc") or e.tag == "loc"]
                sm = "ok"
                count = str(len(locs))
                if len(locs) == 0:
                    sm = "empty"
        except ET.ParseError:
            sm, count = "INVALID XML", "0"
        except Exception as e:
            sm, count = "error (%s)" % type(e).__name__, "?"
        lines.append("| %s | %s | %s | %s | %s |" % (host, status, ms, sm, count))
    lines.append("")
    return lines


# ------------------------------------------------------------------ section b

def _releases(payload):
    out = []
    for result in (payload or {}).get("results", []) or []:
        for rel in result.get("releases", []) or []:
            out.append(rel)
    return out


def _text_of(rel):
    tender = rel.get("tender") or {}
    buyer = rel.get("buyer") or {}
    parts = [
        tender.get("title") or "",
        tender.get("description") or "",
        buyer.get("name") or "",
    ]
    for item in tender.get("items", []) or []:
        addr = (item.get("deliveryAddress") or {})
        parts += [addr.get("region") or "", addr.get("locality") or "",
                  addr.get("postalCode") or ""]
    for party in rel.get("parties", []) or []:
        addr = (party.get("address") or {})
        parts += [addr.get("region") or "", addr.get("locality") or ""]
    return " ".join(parts).lower()


def section_tenders():
    lines = ["## Tender radar -- Contracts Finder, last 7 days", ""]
    today = dt.date.today()
    frm = today - dt.timedelta(days=7)
    releases = []
    warn = None
    try:
        page = 1
        while page <= 5:
            params = {
                "publishedFrom": frm.isoformat() + "T00:00:00",
                "publishedTo": today.isoformat() + "T23:59:59",
                "size": 100,
                "page": page,
            }
            r = _get(OCDS_URL, params=params)
            if r.status_code >= 400:
                warn = "Contracts Finder returned HTTP %s" % r.status_code
                break
            payload = r.json()
            batch = _releases(payload)
            releases += batch
            if len(batch) < 100:
                break
            page += 1
    except Exception as e:
        warn = "Contracts Finder fetch failed (%s: %s)" % (type(e).__name__, e)

    if warn:
        lines.append("> WARNING: %s -- section skipped this week, rest of digest unaffected." % warn)
        lines.append("")
        return lines

    hits, out_of_area = [], 0
    for rel in releases:
        blob = _text_of(rel)
        kw = [k for k in KEYWORDS if k in blob]
        if not kw:
            continue
        if not any(a in blob for a in AREAS):
            out_of_area += 1
            continue
        tender = rel.get("tender") or {}
        value = (tender.get("value") or {}).get("amount")
        closes = (tender.get("tenderPeriod") or {}).get("endDate") or ""
        hits.append({
            "title": tender.get("title") or "(untitled)",
            "buyer": (rel.get("buyer") or {}).get("name") or "",
            "value": ("GBP %s" % f"{int(value):,}") if isinstance(value, (int, float)) else "n/a",
            "closes": closes[:10],
            "kw": ", ".join(kw),
            "ocid": rel.get("ocid") or "",
        })

    lines.append("Scanned %d notices published %s to %s." % (len(releases), frm, today))
    lines.append("")
    if not hits:
        lines.append("No matches in area this week.")
    else:
        for h in hits:
            lines.append("- **%s** -- %s" % (h["title"], h["buyer"]))
            lines.append("  value %s | closes %s | matched: %s" % (h["value"], h["closes"] or "n/a", h["kw"]))
            if h["ocid"]:
                lines.append("  https://www.contractsfinder.service.gov.uk/Search/Results?keyword=%s" % h["ocid"])
    if out_of_area:
        lines.append("")
        lines.append("_%d keyword matches outside the target counties, suppressed._" % out_of_area)
    lines.append("")
    return lines


# ------------------------------------------------------------------ section c

def section_reminders():
    lines = ["## Standing reminders", ""]
    today = dt.date.today()
    for name, due in REMINDERS:
        if due is None:
            lines.append("- %s -- standing check, no fixed date." % name)
            continue
        days = (due - today).days
        if days < 0:
            lines.append("- **%s -- OVERDUE by %d days** (was due %s)." % (name, -days, due))
        elif days <= 60:
            lines.append("- **%s -- due in %d days** (%s)." % (name, days, due))
        else:
            lines.append("- %s -- %s (%d days away)." % (name, due, days))
    lines.append("")
    return lines


# ---------------------------------------------------------------------- main

def post_issue(title, body):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("No GITHUB_TOKEN/GITHUB_REPOSITORY -- printing digest instead.")
        print(body)
        return
    url = "https://api.github.com/repos/%s/issues" % repo
    head = {
        "Authorization": "Bearer %s" % token,
        "Accept": "application/vnd.github+json",
        "User-Agent": HEADERS["User-Agent"],
    }
    for payload in ({"title": title, "body": body, "labels": ["estate-digest"]},
                    {"title": title, "body": body}):
        try:
            r = requests.post(url, headers=head, data=json.dumps(payload), timeout=TIMEOUT)
            if r.status_code < 300:
                print("Issue created: %s" % r.json().get("html_url"))
                return
            print("Issue POST failed %s: %s" % (r.status_code, r.text[:300]))
        except Exception as e:
            print("Issue POST error: %s" % e)
    print(body)


def main():
    today = dt.date.today()
    body = ["_Generated %s UTC by the Estate Monday Digest action._" % dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), ""]
    for fn in (section_sites, section_tenders, section_reminders):
        try:
            body += fn()
        except Exception as e:
            body += ["> WARNING: %s failed (%s: %s)." % (fn.__name__, type(e).__name__, e), ""]
    post_issue("Estate Monday Digest -- %s" % today.isoformat(), "\n".join(body))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # last-resort guard: never fail the workflow
        print("Digest failed at top level: %s: %s" % (type(e).__name__, e))
    sys.exit(0)
