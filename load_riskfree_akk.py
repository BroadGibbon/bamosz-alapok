"""ÁKK referenciahozam CSV/TSV -> risk_free tábla (HUF, 12 hónapos).
A fájlt te töltöd fel a repóba (böngészőből mentett export). A szkript kiszűri
a 12 hónapos sorokat, a Hozam(%)-ot tizedes törtre váltja, és feltölti a Supabase-be.
Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, FILE (alap: riskfree_akk.csv), DRY_RUN=1
"""
import os, sys, csv, io, requests

URL=os.environ.get("SUPABASE_URL","").rstrip("/"); KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
FILE=os.environ.get("FILE","riskfree_akk.csv"); DRY=os.environ.get("DRY_RUN")=="1"

def _hdr():
    return {"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json",
            "Prefer":"resolution=merge-duplicates","Accept-Profile":"public","Content-Profile":"public"}

def sniff_delim(line):
    for d in ["\t",";",","]:
        if d in line: return d
    return ","

def to_float(s):
    s=(s or "").strip().replace("\xa0","").replace(" ","")
    if s.count(",")==1 and s.count(".")==0: s=s.replace(",",".")  # magyar tizedes
    else: s=s.replace(",","")                                      # ezreselválasztó
    try: return float(s)
    except ValueError: return None

def norm_date(s):
    s=(s or "").strip().replace(" ","").replace(".","-").strip("-")
    return s  # 2020.07.08 -> 2020-07-08

def main():
    raw=open(FILE, encoding="utf-8-sig", errors="replace").read()
    first=raw.splitlines()[0]; delim=sniff_delim(first)
    rows=list(csv.reader(io.StringIO(raw), delimiter=delim))
    head=[h.strip().lower() for h in rows[0]]
    def col(name): 
        for i,h in enumerate(head):
            if name in h: return i
        raise SystemExit(f"nem találom az oszlopot: {name} | fejléc={head}")
    ci_d=col("dátum"); ci_t=col("futamidő"); ci_y=col("hozam (%)") if any("hozam (%)"in h for h in head) else col("hozam")
    out={}
    for r in rows[1:]:
        if len(r)<=max(ci_d,ci_t,ci_y): continue
        if r[ci_t].strip().lower()!="12 hónap": continue
        d=norm_date(r[ci_d]); rate=to_float(r[ci_y])
        if not d or rate is None: continue
        out[d]={"currency":"HUF","obs_date":d,"rate":round(rate/100.0,8),"tenor":"12M","source":"ÁKK"}
    recs=list(out.values())
    print(f"12 hónapos sorok: {len(recs)} | elválasztó={delim!r} | első: {recs[0] if recs else '—'}")
    if DRY or not recs: 
        print("(DRY vagy nincs adat — nem írok DB-be)"); return
    if not URL or not KEY: sys.exit("HIÁNYZIK SUPABASE_URL / SUPABASE_SERVICE_KEY")
    for i in range(0,len(recs),1000):
        r=requests.post(f"{URL}/rest/v1/risk_free?on_conflict=currency,obs_date",
                        headers=_hdr(), json=recs[i:i+1000], timeout=90)
        if not r.ok: sys.exit(f"{r.status_code}: {r.text[:200]}")
    print(f"KÉSZ. Feltöltve: {len(recs)} nap (HUF 12M).")

if __name__=="__main__": main()
