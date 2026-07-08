"""BAMOSZ lehúzó — törzslista, alap-részletek, és MINDHÁROM napi idősor:
   árfolyam (price) + nettó eszközérték/AUM (nav) + napi bef.jegy forgalom (turnover).
Egy oldalletöltésből, a ViewState újrahasznosításával (3 POST/alap)."""
import re, json, time, html as H, datetime as dt, requests

BASE="https://www.bamosz.hu"
UA={"User-Agent":"Mozilla/5.0 (research; fund-data)"}
HDR={"Faces-Request":"partial/ajax","X-Requested-With":"XMLHttpRequest",
     "Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"}
# chartType érték, a hozzá tartozó gomb (source), és a céloszlop
CHART_TYPES=[("arfolyam","j_idt243","price"),
             ("nettoeszkoz","j_idt245","nav"),
             ("napibefjegy","j_idt247","turnover")]
_clean=lambda x: H.unescape(re.sub(r"<[^>]+>","",x)).strip()

def _num(s):
    if not s: return None
    s=s.replace("\xa0","").replace(" ","").replace(",",".")
    try: return float(s)
    except ValueError: return None

def _date(s):
    m=re.search(r"(\d{4})\.(\d{2})\.(\d{2})", s or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None

def _session():
    s=requests.Session(); s.headers.update(UA); return s

def fund_list(s=None):
    s=s or _session()
    h=s.get(f"{BASE}/egyes-alapok-kivalasztasa", timeout=40).text
    out={}
    for isin,name in re.findall(r'/alapoldal\?isin=(HU\d{10})"[^>]*>(.*?)</a>', h, re.S):
        out[isin]=H.unescape(re.sub(r"\s+"," ",name)).strip()
    return out

def _labels(h):
    return {_clean(k).rstrip(":"):_clean(v) for k,v in
            re.findall(r'<td class="label">(.*?)</td>\s*<td class="data">(.*?)</td>', h, re.S)}

def _form(h):
    m=re.search(r'<form[^>]*id="([^"]*:j_idt8)"[^>]*action="([^"]*)"', h)
    if not m: return None
    fid, action=m.group(1), H.unescape(m.group(2))
    fi=h.index(m.group(0)); fh=h[fi:h.index("</form>",fi)]
    inp={}
    for mm in re.finditer(r'<input\b[^>]*>', fh):
        n=re.search(r'name="([^"]*)"',mm.group(0))
        if not n: continue
        v=re.search(r'value="([^"]*)"',mm.group(0))
        inp[n.group(1)]=H.unescape(v.group(1)) if v else ""
    return fid, action, inp

def _series(fid, action, base_inp, base, s, chart_type, suf, start, vs):
    """Egy idősor lekérése: {YYYY-MM-DD: érték}."""
    inp=dict(base_inp)
    inp["javax.faces.ViewState"]=vs
    inp[fid+":startDate_input"]=start
    inp[fid+":chartType"]=chart_type
    src=fid+":"+suf
    inp.update({"javax.faces.partial.ajax":"true","javax.faces.source":src,
                "javax.faces.partial.execute":"@all",
                "javax.faces.partial.render":f"{fid}:grafikon {fid}:fundDataTable",
                src:src, fid:fid, "chartType":chart_type})
    resp=s.post(action, data=inp, headers={**HDR,"Referer":base}, timeout=90).text
    m=re.search(r'chartDataValue[^>]*value="(\[\[.*?\]\])"', resp)
    if not m: return {}
    arr=json.loads(m.group(1).replace("&quot;",'"'))
    return {dt.datetime.fromtimestamp(x[0]/1000,dt.timezone.utc).strftime("%Y-%m-%d"):x[1]
            for x in arr}

def fund_page(isin, start="2005.01.01", s=None, retries=3):
    """(dim dict, nav_rows) — nav_rows sorai: isin, obs_date, price, nav, turnover."""
    s=s or _session()
    base=f"{BASE}/alapoldal?isin={isin}"
    last=None
    for attempt in range(retries):
        try:
            h=s.get(base, timeout=40).text
            L=_labels(h)
            if L.get("Alap neve"):
                dim={"isin":isin,
                     "name":L.get("Alap neve"),
                     "series":L.get("Befektetési sorozat megjelölése"),
                     "manager":L.get("Alapkezelő"),
                     "category":L.get("Kategória"),
                     "currency":L.get("Befektetési jegy devizaneme"),
                     "launch_date":_date(L.get("Alap indulási dátuma")),
                     "legal_type":L.get("Jogszabályi típus"),
                     "geo_exposure":L.get("Földrajzi kitettség"),
                     "ccy_exposure":L.get("Devizális kitettség"),
                     "esg":L.get("ESG besorolás") or None,
                     "risk_return":L.get("Hozam/kockázat mutató") or None}
                fid, action, base_inp=_form(h)
                vs=base_inp.get("javax.faces.ViewState")
                rows={}
                for ct,suf,col in CHART_TYPES:
                    for d,val in _series(fid,action,base_inp,base,s,ct,suf,start,vs).items():
                        rows.setdefault(d,{"isin":isin,"obs_date":d,"price":None,"nav":None,"turnover":None})
                        rows[d][col]=val
                if rows:
                    return dim, list(rows.values())
        except Exception as e:
            last=e
        time.sleep(1.5*(attempt+1)); s=_session()
    raise RuntimeError(f"{isin}: nem sikerült betölteni ({last})")
