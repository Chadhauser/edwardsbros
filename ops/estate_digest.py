#!/usr/bin/env python3
"""Estate Monday Digest (S1 + S4).

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
import time
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

# Area terms -- target counties plus their main towns.
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
MAX_PAGES = 20            # stages=tender filters server-side, so this is ample
PAGE_PAUSE = 1.5          # be a good citizen; the service rate-limits hard
BACKOFF = (10, 30, 60)    # seconds to wait after a 429 before retrying

# ----------------------------------------------------------- (c) reminders

REMINDERS = [
    ("Disavow file refresh", dt.date(2026, 11, 1)),
    ("Ahrefs cancellation check", None),  # standing monthly check
]


def _get(url, **kw):
    if requests is None:
        raise RuntimeError("requests unavailable")
    return requests.get(url, timeout=TIMEOUT, headers=HEADERS, **kw)


def _get_polite(url, **kw):
    """GET with backoff on 429/503. Returns the last response either way."""
    r = _get(url, **kw)
    for wait in BACKOFF:
        if r.status_code not in (429, 503):
            return r
        time.sleep(wait)
        r = _get(url, **kw)
    return r


def _get_retry(url, attempts=3, pause=4, **kw):
    """GET with a couple of retries -- avoids false DOWN calls on cold starts."""
    last = None
    for i in range(attempts):
        try:
            r = _get(url, **kw)
            if r.status_code < 400:
                return r, None
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = type(e).__name__
        if i < attempts - 1:
            time.sleep(pause)
    return None, last


# ------------------------------------------------------------------ section a

def _sitemap_state(base):
    """Return (state, url_count) for a site's sitemap."""
    r, err = _get_retry(base.rstrip("/") + "/sitemap.xml", allow_redirects=True)
    if r is None:
        return "unreachable (%s)" % err, "?"
    body = (r.content or b"").lstrip()
    ctype = (r.headers.get("Content-Type") or "").lower()
    looks_xml = body.startswith(b"<?xml") or body.startswith(b"<urlset") or body.startswith(b"<sitemapindex")
    if not looks_xml:
        if b"<html" in body[:400].lower() or "html" in ctype:
            return "BLOCKED/HTML (%s)" % r.status_code, "0"
        return "NOT XML (%s)" % r.status_code, "0"
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return "INVALID XML", "0"
    locs = [e for e in root.iter() if e.tag.endswith("}loc") or e.tag == "loc"]
    return ("ok" if locs else "EMPTY"), str(len(locs))


def section_sites():
    lines = ["## Sites", ""]
    lines.append("| Site | Status | ms | Sitemap | URLs |")
    lines.append("| --- | --- | --- | --- | --- |")
    for base in SITES:
        host = base.replace("https://", "")
        r, err = _get_retry(base, allow_redirects=True)
        if r is None:
            status, ms = "**DOWN**", err
        else:
            status = str(r.status_code)
            ms = str(int(r.elapsed.total_seconds() * 1000))
        sm, count = _sitemap_state(base)
        lines.append("| %s | %s | %s | %s | %s |" % (host, status, ms, sm, count))
    lines.append("")
    return lines


# ------------------------------------------------------------------ section b

def _releases(payload):
    """Contracts Finder returns releases at the top level; tolerate both shapes."""
    if not isinstance(payload, dict):
        return []
    out = list(payload.get("releases") or [])
    for result in payload.get("results", []) or []:
        out += list(result.get("releases") or [])
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
        addrs = list(item.get("deliveryAddresses") or [])
        if isinstance(item.get("deliveryAddress"), dict):
            addrs.append(item["deliveryAddress"])
        for addr in addrs:
            if isinstance(addr, dict):
                parts += [addr.get("region") or "", addr.get("locality") or "",
                          addr.get("postalCode") or "", addr.get("streetAddress") or ""]
    for party in rel.get("parties", []) or []:
        addr = party.get("address") or {}
        if ("buyer" in (party.get("roles") or [])) or not party.get("roles"):
            parts += [party.get("name") or "", addr.get("region") or "",
                      addr.get("locality") or "", addr.get("streetAddress") or ""]
    return " ".join(parts).lower()


def _is_live_opportunity(rel, today):
    """Keep open invitations to tender; drop awards and closed notices."""
    tags = [t.lower() for t in (rel.get("tag") or [])]
    if not any(t.startswith("tender") for t in tags):
        return False
    tender = rel.get("tender") or {}
    if (tender.get("status") or "").lower() not in ("", "active", "planning"):
        return False
    end = ((tender.get("tenderPeriod") or {}).get("endDate") or "")[:10]
    if end:
        try:
            if dt.date.fromisoformat(end) < today:
                return False
        except Exception:
            pass
    return True


def section_tenders():
    lines = ["## Tender radar -- Contracts Finder, last 7 days", ""]
    today = dt.date.today()
    frm = today - dt.timedelta(days=7)
    releases = []
    warn = None
    truncated = False
    pages_done = 0
    try:
        for page in range(1, MAX_PAGES + 1):
            params = {
                "publishedFrom": frm.isoformat() + "T00:00:00",
                "publishedTo": today.isoformat() + "T23:59:59",
                "stages": "tender",
                "size": 100,
                "page": page,
            }
            r = _get_polite(OCDS_URL, params=params)
            if r.status_code >= 400:
                if releases:
                    truncated = True
                else:
                    warn = "Contracts Finder returned HTTP %s" % r.status_code
                break
            batch = _releases(r.json())
            releases += batch
            pages_done = page
            if len(batch) < 100:
                break
            if page == MAX_PAGES:
                truncated = True
            time.sleep(PAGE_PAUSE)
    except Exception as e:
        if not releases:
            warn = "Contracts Finder fetch failed (%s: %s)" % (type(e).__name__, e)
        else:
            truncated = True

    if warn:
        lines.append("> WARNING: %s -- section skipped this week, rest of digest unaffected." % warn)
        lines.append("")
        return lines

    live = [r for r in releases if _is_live_opportunity(r, today)]
    hits, out_of_area = [], []
    seen = set()
    for rel in live:
        blob = _text_of(rel)
        kw = [k for k in KEYWORDS if k in blob]
        if not kw:
            continue
        ocid = rel.get("ocid") or ""
        if ocid and ocid in seen:
            continue
        seen.add(ocid)
        tender = rel.get("tender") or {}
        value = (tender.get("value") or {}).get("amount")
        url = ""
        for doc in tender.get("documents", []) or []:
            if "contractsfinder" in (doc.get("url") or ""):
                url = doc["url"]
                break
        row = {
            "title": tender.get("title") or "(untitled)",
            "buyer": (rel.get("buyer") or {}).get("name") or "",
            "value": ("GBP {:,.0f}".format(value)) if isinstance(value, (int, float)) and value else "n/a",
            "closes": ((tender.get("tenderPeriod") or {}).get("endDate") or "")[:10],
            "kw": ", ".join(kw),
            "url": url,
        }
        if any(a in blob for a in AREAS):
            hits.append(row)
        else:
            out_of_area.append(row)

    lines.append("Scanned %d tender-stage notices over %d page(s), published %s to %s (%d still open)."
                 % (len(releases), pages_done, frm, today, len(live)))
    if truncated:
        lines.append("")
        lines.append("> Note: fetch stopped early (page cap or rate limit); some notices in the window may be missed.")
    lines.append("")
    if not hits:
        lines.append("No matches in area this week.")
    else:
        for h in hits:
            lines.append("- **%s** -- %s" % (h["title"], h["buyer"]))
            lines.append("  value %s | closes %s | matched: %s" % (h["value"], h["closes"] or "n/a", h["kw"]))
            if h["url"]:
                lines.append("  %s" % h["url"])
    if out_of_area:
        lines.append("")
        lines.append("<details><summary>%d keyword matches outside the target counties</summary>" % len(out_of_area))
        lines.append("")
        for h in out_of_area[:25]:
            lines.append("- %s -- %s (closes %s, matched: %s)"
                         % (h["title"], h["buyer"], h["closes"] or "n/a", h["kw"]))
        lines.append("")
        lines.append("</details>")
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


# ------------------------------------------------------------- section d (S4)

def section_registrar():
    """Obligations lookahead. Lives in ops/registrar.py."""
    from registrar import section_registrar as _reg
    return _reg()


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
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    today = dt.date.today()
    body = ["_Generated %s UTC by the Estate Monday Digest action._"
            % dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), ""]
    for fn in (section_registrar, section_sites, section_tenders, section_reminders):
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
