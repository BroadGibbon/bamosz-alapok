"""EUR (ECB) és USD (US Treasury) 1 éves kockázatmentes hozam -> risk_free tábla.
Teljesen automatikus, publikus forrásokból. Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, DRY_RUN=1
"""
import os, sys, csv, io, datetime as dt, requests

URL=os.environ.get("SUPABASE_URL","").rstrip("/"); KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
DRY=os.environ.get("DRY_RUN")=="1"
START_YEAR=2020
UA={"User-Agent":"Mozilla/5.0 (research; fund-data)"}

def _hdr():
    return {"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json",
            "Prefer":"resolution=merge-duplicates","Accept-Profile":"public","Content-Profile":"public"}

def fetch_usd():
    """US Treasury napi par yield curve, '1 Yr' oszlop, évenként."""
    out={}
    for yr in range(START_YEAR, dt.date.today().year+1):
        u=(f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           f"daily-treasury-rates.csv/{yr}/all?type=daily_treasury_yield_curve"
           f"&field_tdr_date_value={yr}&page&_format=csv")
        r=requests.get(u, headers=UA, timeout=60); r.raise_for_status()
        rows=list(csv.reader(io.StringIO(r.text)))
        head=rows[0]; di=head.index("Date"); yi=head.index("1 Yr")
        for row in rows[1:]:
            if len(row)<=max(di,yi) or not row[yi].strip(): continue
            m,d,y=row[di].split("/")
            iso=f"{y}-{m}-{d}"
            out[iso]={"currency":"USD","obs_date":iso,"rate":round(float(row[yi])/100,8),
                      "tenor":"1Y","source":"US Treasury"}
    return list(out.values())

def fetch_eur():
    """ECB AAA államkötvény 1 éves spot ráta (SR_1Y)."""
    u=("https://data-api.ecb.europa.eu/service/data/YC/"
       "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y"
       f"?startPeriod={START_YEAR}-01-01&format=csvdata")
    r=requests.get(u, headers=UA, timeout=60); r.raise_for_status()
    out=[]
    for row in csv.DictReader(io.StringIO(r.text)):
        d=row.get("TIME_PERIOD"); v=row.get("OBS_VALUE")
        if not d or not v: continue
        out.append({"currency":"EUR","obs_date":d,"rate":round(float(v)/100,8),
                    "tenor":"1Y","source":"ECB"})
    return out

def upsert(recs):
    for i in range(0,len(recs),1000):
        r=requests.post(f"{URL}/rest/v1/risk_free?on_conflict=currency,obs_date",
                        headers=_hdr(), json=recs[i:i+1000], timeout=90)
        if not r.ok: sys.exit(f"{r.status_code}: {r.text[:200]}")

def main():
    usd=fetch_usd(); eur=fetch_eur()
    print(f"USD: {len(usd)} nap | {usd[0]['obs_date']}..{usd[-1]['obs_date']} | pl. {usd[-1]}")
    print(f"EUR: {len(eur)} nap | {eur[0]['obs_date']}..{eur[-1]['obs_date']} | pl. {eur[-1]}")
    if DRY: print("(DRY — nem írok DB-be)"); return
    if not URL or not KEY: sys.exit("HIÁNYZIK SUPABASE_URL / SUPABASE_SERVICE_KEY")
    upsert(usd); upsert(eur)
    print(f"KÉSZ. Feltöltve: USD {len(usd)} + EUR {len(eur)} nap.")

if __name__=="__main__": main()
