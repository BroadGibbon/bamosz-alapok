"""ECB napi árfolyamok -> fx_rate tábla: huf_per_unit devizánként.
HUF=1; EUR=HUF/EUR; USD/CZK/PLN/CHF = (HUF/EUR) / (deviza/EUR). Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, DRY_RUN=1
"""
import os, sys, csv, io, requests
URL=os.environ.get("SUPABASE_URL","").rstrip("/"); KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
DRY=os.environ.get("DRY_RUN")=="1"; START=2020
CCYS=["USD","CZK","PLN","CHF"]   # EUR és HUF külön
UA={"User-Agent":"Mozilla/5.0 (research; fund-data)"}

def _hdr():
    return {"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json",
            "Prefer":"resolution=merge-duplicates","Accept-Profile":"public","Content-Profile":"public"}

def ecb(ccy):
    u=(f"https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A"
       f"?startPeriod={START}-01-01&format=csvdata")
    r=requests.get(u, headers=UA, timeout=60); r.raise_for_status()
    out={}
    for row in csv.DictReader(io.StringIO(r.text)):
        d=row.get("TIME_PERIOD"); v=row.get("OBS_VALUE")
        if d and v:
            try: out[d]=float(v)
            except ValueError: pass
    return out

def build():
    eur_huf=ecb("HUF")           # HUF / 1 EUR
    recs=[]
    # HUF
    for d in eur_huf: recs.append({"currency":"HUF","obs_date":d,"huf_per_unit":1.0})
    # EUR
    for d,hufeur in eur_huf.items():
        recs.append({"currency":"EUR","obs_date":d,"huf_per_unit":round(hufeur,6)})
    # USD/CZK/PLN/CHF keresztárfolyam
    for ccy in CCYS:
        eur_c=ecb(ccy)           # ccy / 1 EUR
        for d,cval in eur_c.items():
            if d in eur_huf and cval:
                recs.append({"currency":ccy,"obs_date":d,
                             "huf_per_unit":round(eur_huf[d]/cval,6)})
    return recs

def main():
    recs=build()
    from collections import Counter
    c=Counter(r["currency"] for r in recs)
    print("Sorok devizánként:", dict(c))
    # minta a legutolsó közös napra
    for ccy in ["EUR","USD","CHF","PLN","CZK"]:
        last=max((r for r in recs if r["currency"]==ccy), key=lambda r:r["obs_date"])
        print(f"  1 {ccy} = {last['huf_per_unit']:.2f} HUF ({last['obs_date']})")
    if DRY: print("(DRY — nincs feltöltés)"); return
    if not URL or not KEY: sys.exit("HIÁNYZIK SUPABASE_URL / SUPABASE_SERVICE_KEY")
    for i in range(0,len(recs),1000):
        r=requests.post(f"{URL}/rest/v1/fx_rate?on_conflict=currency,obs_date",
                        headers=_hdr(), json=recs[i:i+1000], timeout=90)
        if not r.ok: sys.exit(f"{r.status_code}: {r.text[:200]}")
    print(f"KÉSZ. Feltöltve: {len(recs)} árfolyam-sor.")

if __name__=="__main__": main()
