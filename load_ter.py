"""MNB TER-fájl -> fund_ter tábla (AK díj/SÁNE és TER 2024, alaponként, ISIN alapján).
A fájlt te töltöd fel a repóba (böngészőből mentett CSV). ISIN alapján párosít a fund_dim-hez.
Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, FILE (alap: mnb_ter.csv), YEAR (alap 2024), DRY_RUN=1
"""
import os, sys, csv, io, re, requests
URL=os.environ.get("SUPABASE_URL","").rstrip("/"); KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
FILE=os.environ.get("FILE","mnb_ter.csv"); YEAR=int(os.environ.get("YEAR","2024")); DRY=os.environ.get("DRY_RUN")=="1"
ISIN_RE=re.compile(r'\b([A-Z]{2}\d{10})\b')

def _hdr():
    return {"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json",
            "Prefer":"resolution=merge-duplicates","Accept-Profile":"public","Content-Profile":"public"}
def sniff(line):
    for d in ["\t",";",","]:
        if d in line: return d
    return ","
def to_float(s):
    s=(s or "").strip().replace("\xa0","").replace(" ","")
    if not s: return None
    if s.count(",")==1 and s.count(".")==0: s=s.replace(",",".")
    else: s=s.replace(",","")
    try: return float(s)
    except ValueError: return None

def parse():
    raw=open(FILE,encoding="utf-8-sig",errors="replace").read()
    delim=sniff(raw.splitlines()[0])
    allrows=list(csv.reader(io.StringIO(raw),delimiter=delim))
    hi=next((i for i,r in enumerate(allrows[:15]) if any("isin" in (c or "").lower() for c in r)), 0)
    rows=allrows[hi:]
    head=[h.strip().lower().replace("\n"," ") for h in rows[0]]
    def find(pred,label):
        for i,h in enumerate(head):
            if pred(h): return i
        sys.exit(f"nem találom: {label} | fejléc={head}")
    ci_isin=find(lambda h:"isin" in h,"ISIN")
    ci_ak  =find(lambda h:"sáne" in h and "alapkezel" in h,"Alapkezelési díj/SÁNE")
    ci_ter =find(lambda h:"ter" in h and "2024" in h,"TER 2024")
    recs=[]
    for r in rows[1:]:
        if len(r)<=max(ci_isin,ci_ak,ci_ter): continue
        m=ISIN_RE.search((r[ci_isin] or "").upper())
        if not m: continue
        ak=to_float(r[ci_ak]); ter=to_float(r[ci_ter])
        recs.append({"isin":m.group(1),"ter_year":YEAR,
                     "ak_dij": round(ak/100,6) if ak is not None else None,
                     "ter":    round(ter/100,6) if ter is not None else None})
    return recs, delim

def main():
    recs,delim=parse()
    print(f"Beolvasott ISIN-sorok: {len(recs)} | elválasztó={delim!r}")
    print("minta:", recs[:3])
    if DRY: print("(DRY — nincs párosítás/feltöltés)"); return
    if not URL or not KEY: sys.exit("HIÁNYZIK SUPABASE_URL / SUPABASE_SERVICE_KEY")
    # isin -> fund_id térkép a fund_dim-ből
    fmap={}
    off=0
    while True:
        r=requests.get(f"{URL}/rest/v1/fund_dim?select=fund_id,isin&limit=1000&offset={off}",
                       headers={**_hdr(),"Range-Unit":"items"}, timeout=60); r.raise_for_status()
        chunk=r.json()
        if not chunk: break
        for row in chunk: fmap[row["isin"]]=row["fund_id"]
        off+=1000
        if len(chunk)<1000: break
    out=[]; unmatched=0
    for x in recs:
        fid=fmap.get(x["isin"])
        if fid is None: unmatched+=1; continue
        out.append({"fund_id":fid,"ter_year":x["ter_year"],"ak_dij":x["ak_dij"],"ter":x["ter"]})
    print(f"Párosítva: {len(out)} | nem találtam a DB-ben: {unmatched}")
    for i in range(0,len(out),1000):
        r=requests.post(f"{URL}/rest/v1/fund_ter?on_conflict=fund_id,ter_year",
                        headers=_hdr(), json=out[i:i+1000], timeout=90)
        if not r.ok: sys.exit(f"{r.status_code}: {r.text[:200]}")
    print(f"KÉSZ. Feltöltve: {len(out)} alap TER-adata ({YEAR}).")

if __name__=="__main__": main()
