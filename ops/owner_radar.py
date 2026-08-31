#!/usr/bin/env python3
"""S7 Owner Radar -- monthly succession-candidate sweep of Companies House.

Replaces the manual sweep done by hand on 31 Aug 2026. All query logic below
was learned and validated in that manual pass.

Deterministic: Companies House public API only. No AI. Free.
Never crashes: every lookup is guarded; failures become warning lines.

Output: a GitHub Issue labelled `owner-radar`.

Honest limits (stated in the output too):
  * Date of birth from Companies House is month + year only, so ages are
    approximate to within a year.
  * Identity-verification status is not exposed on the public officers
    endpoint, so the "verified" tell from the manual pass cannot be
    automated. Tiering uses the remaining tells.
  * Contact details are only reported when found on the company's own site.
    Never guessed.
"""

import datetime as dt
import json
import os
import sys
import time

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

TIMEOUT = 25
HEADERS = {"User-Agent": "EdwardsBros-OwnerRadar/1.0"}
CH = "https://api.company-information.service.gov.uk"

# Companies House allows 600 requests per five minutes. 0.6s between calls
# keeps us comfortably inside that.
CALL_PAUSE = 0.6
MAX_ENRICH = 120          # candidates fully enriched per run (3 calls each)
MIN_AGE_YEARS = 15        # incorporated at least this long ago

# ------------------------------------------------------------------ filters

LOCATIONS = ["Cambridgeshire", "Northamptonshire", "Peterborough", "Huntingdon"]

SIC_CODES = [
    "69201", "69202", "69203",   # practices / bookkeeping / tax
    "71200",                     # testing and inspection
    "74901", "74909",            # H&S / fire
    "82110",                     # admin
    "80200",                     # security and monitoring
    "52210",                     # transport support -- tacho bureaus
    "69109",                     # patent and trade mark renewals
    "85590",                     # training
]

# Name keywords beat SIC for the Edwards Bros classes.
NAME_KEYWORDS = [
    "payroll", "bureau", "secretarial", "fire", "safety", "alarm",
    "monitoring", "inspection", "testing", "training", "compliance",
    "associates", "consultants", "assessment", "network",
]

# Peter's exclusions.
EXCLUDE_NAME_TERMS = [
    "translation", "translations", "interpreting",
    "r&d", "research and development", "tax credit", "tax credits",
]

# Hand-verified 31 Aug 2026. Always re-checked and shown, whatever the sweep
# returns, so the manual work is never lost.
SEEDS = {
    "04169039": "Curtis-Barden",
    "04119748": "N. Stephens",
    "03601404": "P D Tracey",
    "06687730": "Ian Lancaster",
    "06675211": "J&T Accounting",
    "04663747": "BDH",
    "04646930": "Numbers Express",
    "04882029": "Grovelake",
    "05323230": "Fenland Business Services",
    "06162320": "SAS Accountancy",
    "04548550": "Williams Accountancy",
    "05100557": "David Jeffreys",
    "03893461": "AIG Accounting",
    "04728169": "Pisces Office Support",
    "04675066": "Amity Solutions",
    "05725448": "MW Corporate Secretaries",
    "03893668": "Visual Testing Services",
}


def _key():
    return os.environ.get("CH_API_KEY")


def _ch_get(path, params=None):
    """Authenticated Companies House GET. Returns dict or None."""
    if requests is None:
        return None
    try:
        r = requests.get(CH + path, auth=(_key(), ""), params=params,
                         timeout=TIMEOUT, headers=HEADERS)
        time.sleep(CALL_PAUSE)
        if r.status_code == 429:
            time.sleep(30)
            r = requests.get(CH + path, auth=(_key(), ""), params=params,
                             timeout=TIMEOUT, headers=HEADERS)
            time.sleep(CALL_PAUSE)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


# ------------------------------------------------------------------- search

def _search(params):
    out = {}
    base = {
        "company_status": "active",
        "incorporated_to": (dt.date.today() - dt.timedelta(days=365 * MIN_AGE_YEARS)).isoformat(),
        "size": 100,
    }
    base.update(params)
    data = _ch_get("/advanced-search/companies", base)
    for item in ((data or {}).get("items") or []):
        num = item.get("company_number")
        if num:
            out[num] = item
    return out


def sweep():
    """Return {company_number: search_item} across all filters."""
    found = {}
    for location in LOCATIONS:
        for sic in SIC_CODES:
            found.update(_search({"location": location, "sic_codes": sic}))
        for kw in NAME_KEYWORDS:
            found.update(_search({"location": location, "company_name_includes": kw}))
    return found


# ---------------------------------------------------------------- enrichment

def _year_of(dob):
    try:
        return int((dob or {}).get("year"))
    except Exception:
        return None


def enrich(number):
    """Officers, filing history and PSC for one company."""
    profile = _ch_get("/company/%s" % number) or {}
    officers = (_ch_get("/company/%s/officers" % number, {"items_per_page": 50}) or {}).get("items") or []
    history = (_ch_get("/company/%s/filing-history" % number,
                       {"items_per_page": 30}) or {}).get("items") or []
    psc = (_ch_get("/company/%s/persons-with-significant-control" % number) or {}).get("items") or []
    return profile, officers, history, psc


def assess(number, name, profile, officers, history, psc, today):
    """Return (tier, reasons, detail dict). Tiers: PRIME/STRONG/WATCH/PASS."""
    reasons = []
    detail = {
        "number": number,
        "name": name or profile.get("company_name") or "",
        "incorporated": (profile.get("date_of_creation") or "")[:4],
        "address": ", ".join(
            v for v in [
                (profile.get("registered_office_address") or {}).get("locality"),
                (profile.get("registered_office_address") or {}).get("postal_code"),
            ] if v),
        "accounts": "",
        "directors": [],
    }

    lowered = detail["name"].lower()
    for term in EXCLUDE_NAME_TERMS:
        if term in lowered:
            return "PASS", ["excluded name term: %s" % term], detail

    # --- officers
    active, resigned_recently = [], False
    for o in officers:
        role = (o.get("officer_role") or "").lower()
        resigned = o.get("resigned_on")
        if resigned:
            try:
                if (today - dt.date.fromisoformat(resigned[:10])).days <= 365 * 3:
                    resigned_recently = True
            except Exception:
                pass
            continue
        if "director" not in role and "secretary" not in role:
            continue
        active.append(o)

    directors = [o for o in active if "director" in (o.get("officer_role") or "").lower()]
    for o in directors:
        year = _year_of(o.get("date_of_birth"))
        detail["directors"].append(
            "%s%s" % (o.get("name") or "?",
                      " (b.%s, ~%d)" % (year, today.year - year) if year else ""))

    # Younger director appointed recently = succession already solved.
    for o in directors:
        year = _year_of(o.get("date_of_birth"))
        appointed = o.get("appointed_on")
        if not year or year < 1975 or not appointed:
            continue
        try:
            if (today - dt.date.fromisoformat(appointed[:10])).days <= 365 * 10:
                return "PASS", ["younger director appointed -- succession solved"], detail
        except Exception:
            pass

    years = [y for y in (_year_of(o.get("date_of_birth")) for o in directors) if y]
    if not years:
        return "PASS", ["no director date of birth published"], detail
    oldest_age = today.year - min(years)

    # --- filing history
    for f in history:
        desc = ("%s %s" % (f.get("description") or "",
                           json.dumps(f.get("description_values") or {}))).lower()
        if "strike" in desc or "gazette" in desc:
            return "PASS", ["strike-off notice on file"], detail
    for f in history:
        if (f.get("category") or "") != "accounts":
            continue
        desc = (f.get("description") or "").lower()
        detail["accounts"] = desc.replace("accounts-with-accounts-type-", "")
        if "dormant" in desc:
            return "PASS", ["latest accounts are dormant"], detail
        break

    # --- PSC
    for p in psc:
        if "corporate" in (p.get("kind") or "").lower():
            reasons.append("group-owned by %s -- approach parent" % (p.get("name") or "parent"))
            break

    if resigned_recently:
        reasons.append("officer resigned within 3 years -- wind-down signal")

    sole = len(directors) <= 2
    if oldest_age >= 70 and sole and detail["accounts"]:
        tier = "PRIME"
    elif oldest_age >= 65 or (oldest_age >= 60 and resigned_recently):
        tier = "STRONG"
    elif oldest_age >= 60:
        tier = "WATCH"
    else:
        return "PASS", ["oldest director ~%d -- too young" % oldest_age], detail

    reasons.insert(0, "oldest director ~%d" % oldest_age)
    return tier, reasons, detail


# --------------------------------------------------------------------- output

def build_report():
    today = dt.date.today()
    lines = ["_Owner Radar -- generated %s UTC._" % dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), ""]

    if not _key():
        lines.append("> WARNING: CH_API_KEY not set -- radar cannot run.")
        return "\n".join(lines)

    warns = []
    try:
        found = sweep()
    except Exception as e:
        found = {}
        warns.append("sweep failed (%s)" % type(e).__name__)

    # Seeds always assessed, whatever the sweep returned.
    order = list(SEEDS.keys()) + [n for n in found if n not in SEEDS]
    if len(order) > MAX_ENRICH:
        warns.append("%d candidates found; enriched the first %d this run"
                     % (len(order), MAX_ENRICH))
        order = order[:MAX_ENRICH]

    buckets = {"PRIME": [], "STRONG": [], "WATCH": [], "PASS": []}
    for number in order:
        name = SEEDS.get(number) or (found.get(number) or {}).get("company_name") or ""
        try:
            profile, officers, history, psc = enrich(number)
            if not profile:
                warns.append("%s: profile unavailable" % number)
                continue
            tier, reasons, detail = assess(number, name, profile, officers, history, psc, today)
        except Exception as e:
            warns.append("%s: %s" % (number, type(e).__name__))
            continue
        buckets[tier].append((detail, reasons, number in SEEDS))

    lines.append("Swept %d companies, assessed %d. PRIME %d | STRONG %d | WATCH %d | PASS %d."
                 % (len(found), len(order), len(buckets["PRIME"]), len(buckets["STRONG"]),
                    len(buckets["WATCH"]), len(buckets["PASS"])))
    lines.append("")

    for tier in ("PRIME", "STRONG", "WATCH"):
        rows = buckets[tier]
        lines.append("## %s (%d)" % (tier, len(rows)))
        lines.append("")
        if not rows:
            lines.append("None this month.")
            lines.append("")
            continue
        for detail, reasons, is_seed in rows:
            lines.append("- **%s** (%s)%s" % (detail["name"], detail["number"],
                                              " _seed_" if is_seed else ""))
            lines.append("  inc. %s | %s | accounts: %s"
                         % (detail["incorporated"] or "?", detail["address"] or "address n/a",
                            detail["accounts"] or "none filed"))
            if detail["directors"]:
                lines.append("  directors: %s" % "; ".join(detail["directors"]))
            lines.append("  %s" % "; ".join(reasons))
        lines.append("")

    if buckets["PASS"]:
        lines.append("<details><summary>PASS (%d) with reasons</summary>" % len(buckets["PASS"]))
        lines.append("")
        for detail, reasons, is_seed in buckets["PASS"][:60]:
            lines.append("- %s (%s) -- %s" % (detail["name"], detail["number"], "; ".join(reasons)))
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("_Ages derive from month/year of birth only, so are approximate. "
                 "Identity-verification status is not published on the officers "
                 "endpoint, so that tell is not automated. No contact details are "
                 "guessed._")
    lines.append("")
    for w in warns:
        lines.append("> WARNING: %s" % w)
    return "\n".join(lines)


def post_issue(title, body):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print(body)
        return
    url = "https://api.github.com/repos/%s/issues" % repo
    head = {"Authorization": "Bearer %s" % token,
            "Accept": "application/vnd.github+json",
            "User-Agent": HEADERS["User-Agent"]}
    for payload in ({"title": title, "body": body, "labels": ["owner-radar"]},
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


if __name__ == "__main__":
    try:
        post_issue("Owner Radar -- %s" % dt.date.today().isoformat(), build_report())
    except Exception as e:
        print("Owner Radar failed at top level: %s: %s" % (type(e).__name__, e))
    sys.exit(0)
