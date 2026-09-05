#!/usr/bin/env python3
"""Distress Radar - the 'Commerce Windows treatment', as code.
Usage: CH_API_KEY=xxx python3 distress_check.py 04699391
       (or: python3 distress_check.py --facts facts.json  for offline scoring)
Scores a UK company's latest small-company accounts for financial pressure.
Public data only. Output is factual flags; never characterise a company publicly."""
import sys, json, base64, urllib.request

W = {
 "cash_starved":25,"net_liabilities":20,"creditor_stretch":15,"pension_arrears":8,
 "director_support":10,"family_creditors":8,"bank_to_family":5,"dta_on_losses":4,
 "related_party_props":5,
}

def score(f):
    flags=[]; granton=[]
    cash=f.get("cash",0); cred1=f.get("creditors_lt_1yr") or 1
    if cash < 0.05*cred1: flags.append(("cash_starved",f"cash £{cash:,.0f} vs creditors<1yr £{cred1:,.0f}"))
    if f.get("net_assets",0) < 0: flags.append(("net_liabilities",f"net liabilities £{-f['net_assets']:,.0f}"))
    tc,tc_p=f.get("trade_creditors"),f.get("trade_creditors_prior")
    if tc and tc_p and tc > 1.3*tc_p:
        flags.append(("creditor_stretch",f"trade creditors +{(tc/tc_p-1)*100:.0f}% YoY"))
    if f.get("pension_arrears"): flags.append(("pension_arrears",f"unpaid pension contributions £{f['pension_arrears']:,.0f}"))
    if f.get("director_support_note"): flags.append(("director_support","going concern rests on director's personal support"))
    oc=f.get("other_creditors",0)
    if oc > 0.5*cred1: flags.append(("family_creditors",f"'other creditors' £{oc:,.0f} = {oc/cred1*100:.0f}% of current creditors (likely director/family loans)"))
    bb,bb_p=f.get("bank_gt_1yr",0),f.get("bank_gt_1yr_prior",0)
    if bb_p>0 and bb==0 and oc>=f.get("other_creditors_prior",0): flags.append(("bank_to_family","long-term bank debt cleared while informal creditors held/grew"))
    if f.get("deferred_tax_asset",0)>10000: flags.append(("dta_on_losses",f"deferred tax asset £{f['deferred_tax_asset']:,.0f} implies accumulated losses"))
    if f.get("related_party_premises"): flags.append(("related_party_props","premises via related party (rent waived/informal)"))
    if f.get("trade_debtors",0)>=30000: granton.append(f"debtor book £{f['trade_debtors']:,.0f} - invoice-finance candidate")
    s=min(100,sum(W[k] for k,_ in flags))
    return s,flags,granton

def report(name,number,f):
    s,flags,granton=score(f)
    band="HIGH" if s>=60 else "MEDIUM" if s>=35 else "LOW"
    out=[f"== {name} ({number}) — pressure score {s}/100 [{band}]"]
    out+= [f"  • {k}: {d}" for k,d in flags] or ["  • no pressure flags"]
    if granton: out+= ["  → Granton: "+g for g in granton]
    return "\n".join(out)

def fetch_live(number,key):
    import re
    def get(u):
        r=urllib.request.Request(u,headers={"Authorization":"Basic "+base64.b64encode((key+":").encode()).decode()})
        return urllib.request.urlopen(r,timeout=30).read()
    prof=json.loads(get(f"https://api.company-information.service.gov.uk/company/{number}"))
    fh=json.loads(get(f"https://api.company-information.service.gov.uk/company/{number}/filing-history?category=accounts&items_per_page=5"))
    doc=None
    for it in fh.get("items",[]):
        if it.get("links",{}).get("document_metadata"): doc=it["links"]["document_metadata"]; break
    if not doc: raise SystemExit("no accounts document found")
    meta=json.loads(get(doc))
    xhtml=None
    if "application/xhtml+xml" in meta.get("resources",{}):
        xhtml=get(meta["links"]["document"]).decode("utf-8","ignore")
    if not xhtml: raise SystemExit("no iXBRL available (image PDF filing) - score manually")
    def fact(tags,prior=False):
        vals=[]
        for t in tags:
            for m in re.finditer(rf'name="[^"]*{t}"[^>]*>([\d,\.]+)<',xhtml): vals.append(float(m.group(1).replace(",","")))
        if len(vals)>=2: return vals[1] if prior else vals[0]
        return vals[0] if vals else 0
    f={"cash":fact(["CashBankOnHand","CashAtBank"]),
       "creditors_lt_1yr":fact(["CreditorsDueWithinOneYear","Creditors"]),
       "net_assets":fact(["NetAssetsLiabilities"]),
       "trade_creditors":fact(["TradeCreditors"]),"trade_creditors_prior":fact(["TradeCreditors"],True),
       "other_creditors":fact(["OtherCreditors"]),"other_creditors_prior":fact(["OtherCreditors"],True),
       "debtors":fact(["Debtors"]),"debtors_prior":fact(["Debtors"],True),
       "trade_debtors":fact(["TradeDebtors"]),
       "stocks":fact(["Stocks"]),"stocks_prior":fact(["Stocks"],True),
       "bank_gt_1yr":fact(["BankBorrowingsAfterOneYear"]),"bank_gt_1yr_prior":fact(["BankBorrowingsAfterOneYear"],True),
       "deferred_tax_asset":fact(["DeferredTaxAsset"]),
       "pension_arrears":fact(["PensionContributionsOutstanding"]),
       "director_support_note":"support" in xhtml.lower() and "director" in xhtml.lower(),
       "related_party_premises":"waived" in xhtml.lower()}
    if 'sign="-"' in xhtml and f["net_assets"]>0: f["net_assets"]=-f["net_assets"]
    return prof.get("company_name",number),f

if __name__=="__main__":
    if "--facts" in sys.argv:
        f=json.load(open(sys.argv[sys.argv.index("--facts")+1]))
        print(report(f.pop("name","(offline)"),f.pop("number","-"),f))
    else:
        import os
        key=os.environ.get("CH_API_KEY") or sys.exit("set CH_API_KEY or use --facts facts.json")
        name,f=fetch_live(sys.argv[1],key)
        print(report(name,sys.argv[1],f))
