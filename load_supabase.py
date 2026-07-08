"""BAMOSZ -> Supabase betöltő.
Környezeti változók:
  SUPABASE_URL          pl. https://xxxx.supabase.co   (kötelező)
  SUPABASE_SERVICE_KEY  a service_role kulcs           (kötelező)
  LIMIT                 hány alapot dolgozzon fel (teszthez, pl. 5; üres = mind)
  START                 legkorábbi dátum yy.mm.dd (alap: ma - 5 év)
  DRY_RUN               ha "1", nem ír adatbázisba, csak kiír
"""
import os, sys, time, datetime as dt, requests
import bamosz

URL=os.environ.get("SUPABASE_URL","").rstrip("/")
KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
LIMIT=int(os.environ["LIMIT"]) if os.environ.get("LIMIT") else None
DRY=os.environ.get("DRY_RUN")=="1"
START=os.environ.get("START") or (dt.date.today()-dt.timedelta(days=365*5+2)).strftime("%Y.%m.%d")

def _hdr(extra=""):
    p="resolution=merge-duplicates"+(","+extra if extra else "")
    return {"apikey":KEY,"Authorization":f"Bearer {KEY}",
            "Content-Type":"application/json","Prefer":p,
            "Accept-Profile":"public","Content-Profile":"public"}

def _check(r):
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:250]}")
    return r

def upsert_dim(dim):
    r=_check(requests.post(f"{URL}/rest/v1/fund_dim?on_conflict=isin",
                    headers=_hdr("return=representation"), json=[dim], timeout=60))
    return r.json()[0]["fund_id"]

def upsert_nav(rows):
    for i in range(0,len(rows),2000):
        _check(requests.post(f"{URL}/rest/v1/fund_nav?on_conflict=fund_id,obs_date",
                        headers=_hdr(), json=rows[i:i+2000], timeout=90))

def main():
    if not DRY and (not URL or not KEY):
        sys.exit("HIÁNYZIK a SUPABASE_URL vagy SUPABASE_SERVICE_KEY!")
    s=bamosz._session()
    funds=list(bamosz.fund_list(s))
    if LIMIT: funds=funds[:LIMIT]
    print(f"Feldolgozandó alapok: {len(funds)} | kezdődátum: {START} | DRY_RUN={DRY}")
    ok=err=0
    for i,isin in enumerate(funds,1):
        try:
            dim,nav=bamosz.fund_page(isin, start=START, s=s)
            if DRY:
                print(f"[{i}/{len(funds)}] {isin} {(dim["name"] or "?")[:35]!r:37} dim=1 nav={len(nav)}")
            else:
                fid=upsert_dim(dim)
                for row in nav: row["fund_id"]=fid; row.pop("isin",None)
                upsert_nav(nav)
                print(f"[{i}/{len(funds)}] {isin} OK (fund_id={fid}, nav={len(nav)})")
            ok+=1
        except Exception as e:
            err+=1; print(f"[{i}/{len(funds)}] {isin} HIBA: {type(e).__name__}: {e}")
        time.sleep(0.6)   # udvarias a BAMOSZ-hoz
    print(f"\nKÉSZ. Sikeres: {ok}, hibás: {err}")

if __name__=="__main__":
    main()
