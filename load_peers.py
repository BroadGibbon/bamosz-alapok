"""Peer group betöltő: melyik alap melyik GRÁNIT alap peer groupjába tartozik.
Excel-oszlopok: Peer név, Peer ISIN (Nem Gránitos), Gránit név, Gránit ISIN (azonos Peer Group).
A Gránit horgony-alapokat is felvesszük saját magukhoz (a group anchor önmaga csoportjába tartozik).
Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, FILE (alap: peers.csv), DRY_RUN=1
"""
import os, sys, csv, io, re, unicodedata, requests
URL=os.environ.get("SUPABASE_URL","").rstrip("/"); KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
FILE=os.environ.get("FILE","peers.csv"); DRY=os.environ.get("DRY_RUN")=="1"
ISIN_RE=re.compile(r'\b([A-Z]{2}\d{10})\b')

def _hdr():
    return {"apikey":KEY,"Authorization":f"Bearer {KEY}","Content-Type":"application/json",
            "Prefer":"resolution=merge-duplicates","Accept-Profile":"public","Content-Profile":"public"}
def sniff(line):
    for d in ["\t",";",","]:
        if d in line: return d
    return ","
def strip_acc(s):
    return "".join(c for c in unicodedata.normalize("NFKD",s) if not unicodedata.combining(c)).lower()

def parse():
    raw=open(FILE,encoding="utf-8-sig",errors="replace").read()
    delim=sniff(raw.splitlines()[0])
    allrows=list(csv.reader(io.StringIO(raw),delimiter=delim))
    hi=next((i for i,r in enumerate(allrows[:15]) if any("isin" in strip_acc(c or "") for c in r)),0)
    rows=allrows[hi:]
    head=[strip_acc(h) for h in rows[0]]
    def find(pred,label):
        for i,h in enumerate(head):
            if pred(h): return i
        sys.exit(f"nem találom az oszlopot: {label} | fejléc={head}")
    ci_peer_isin =find(lambda h:"isin" in h and "nem" in h, "Peer ISIN (Nem Gránit)")
    ci_grp_isin  =find(lambda h:"isin" in h and "azonos" in h, "Gránit ISIN (azonos Peer Group)")
    ci_grp_name  =find(lambda h:"isin" not in h and "azonos" in h and "nev" in h, "Gránit név (azonos Peer Group)")
    mapping={}   # peer_isin -> (group_isin, group_name)
    anchors={}   # group_isin -> group_name
    for r in rows[1:]:
        if len(r)<=max(ci_peer_isin,ci_grp_isin,ci_grp_name): continue
        pm=ISIN_RE.search((r[ci_peer_isin] or "").upper())
        gm=ISIN_RE.search((r[ci_grp_isin] or "").upper())
        if not gm: continue
        gname=(r[ci_grp_name] or "").strip()
        anchors[gm.group(1)]=gname
        if pm: mapping[pm.group(1)]=(gm.group(1), gname)
    # a Gránit horgonyalapok saját magukhoz
    for gi,gn in anchors.items():
        mapping.setdefault(gi,(gi,gn))
    return mapping, anchors

def main():
    mapping,anchors=parse()
    print(f"Peer-hozzárendelések: {len(mapping)} (ebből {len(anchors)} Gránit horgonyalap)")
    ex=list(mapping.items())[:3]
    print("minta:", ex)
    if DRY: print("(DRY — nincs párosítás/feltöltés)"); return
    if not URL or not KEY: sys.exit("HIÁNYZIK SUPABASE_URL / SUPABASE_SERVICE_KEY")
    # isin -> fund_id térkép
    fmap={}; off=0
    while True:
        r=requests.get(f"{URL}/rest/v1/fund_dim?select=fund_id,isin&limit=1000&offset={off}",
                       headers=_hdr(), timeout=60); r.raise_for_status()
        chunk=r.json()
        for row in chunk: fmap[row["isin"]]=row["fund_id"]
        if len(chunk)<1000: break
        off+=1000
    out=[]; missing=0
    for isin,(gi,gn) in mapping.items():
        fid=fmap.get(isin)
        if fid is None: missing+=1; continue
        out.append({"fund_id":fid,"group_isin":gi,"group_name":gn})
    print(f"Párosítva a DB-vel: {len(out)} | nem találtam: {missing}")
    for i in range(0,len(out),1000):
        r=requests.post(f"{URL}/rest/v1/fund_peer_group?on_conflict=fund_id",
                        headers=_hdr(), json=out[i:i+1000], timeout=90)
        if not r.ok: sys.exit(f"{r.status_code}: {r.text[:200]}")
    print(f"KÉSZ. Feltöltve: {len(out)} peer-hozzárendelés.")

if __name__=="__main__": main()
