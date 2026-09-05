# Distress Radar (S9) — engine v1

The "Commerce Windows treatment" as code. Scores UK small-company accounts for
financial pressure from public Companies House data.

**Status: engine built and calibrated.** `python3 distress_check.py --facts commerce_windows_facts.json`
returns 100/100 HIGH with all nine expected flags plus the Granton invoice-finance flag.

**To go live:** set `CH_API_KEY` (free from developer.company-information.service.gov.uk):
`CH_API_KEY=xxx python3 distress_check.py <company-number>`. Live iXBRL tag extraction is
best-effort v1 — expand tag lists as real filings are tested. Weekly SIC×postcode crawl per
the S9 spec is the next stage (automation chat).

**Rules:** public data only · outputs internal · approach letters never characterise a
company's finances (opportunity framing only) · no personal-curiosity lookups in pipelines.
