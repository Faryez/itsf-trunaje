import json, re, time, datetime, urllib.request, urllib.parse, pathlib, sys
import pycountry
from playwright.sync_api import sync_playwright

LIST = "https://tablesoccer.org/tournaments/"
BASE = "https://app.tablesoccer.org"
OUT = pathlib.Path("data/tournaments.json")
CACHE = pathlib.Path("data/geocache.json")
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

LIST_JS = r"""() => {
 const txt=a=>a.textContent.trim().toUpperCase();
 const regs=[...document.querySelectorAll('a')].filter(a=>txt(a)==='REGISTER');
 const rowOf=a=>{let e=a;while(e.parentElement&&[...e.parentElement.querySelectorAll('a')].filter(x=>txt(x)==='REGISTER').length<2)e=e.parentElement;return e;};
 const dateRe=/^\d+(\s*-\s*\d+)?\s+[A-Za-z]{3}/;
 return regs.map(a=>{
  const L=rowOf(a).innerText.split('\n').map(x=>x.trim()).filter(Boolean).filter(x=>!/^(REGISTER|INFO|NEW)$/i.test(x));
  return {name:L[0],cc:L.find(x=>/^[A-Z]{3}$/.test(x))||L.slice(1).find(x=>!dateRe.test(x)&&!/^itsf/i.test(x))||'',date:L.find(x=>dateRe.test(x))||'',url:a.href};
 });
}"""
ADDR_JS = """() => {
 const L=document.body.innerText.split(/[\\n\\t]+/).map(x=>x.trim()).filter(Boolean);
 const i=L.lastIndexOf('Address');
 return i>=0&&L[i+1]?L[i+1]:'';
}"""

def country(cc):
    try:
        return pycountry.countries.get(alpha_3=cc).name
    except Exception:
        return cc

def geocode(q):
    if q in cache:
        return cache[q]
    time.sleep(1.1)
    url = "https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={"User-Agent": "itsf-turnaje-mapa/1.0 (GitHub Actions)"})
    try:
        j = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        print("geocode fail", q, e); return None
    cache[q] = {"lat": float(j[0]["lat"]), "lon": float(j[0]["lon"])} if j else None
    return cache[q]

def loose(addr):
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    for k in range(len(parts)):
        g = geocode(", ".join(parts[k:]))
        if g:
            return {**g, "approx": k > 0}
    return None

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(
        viewport={"width": 1400, "height": 900},
        locale="en-US",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    page = ctx.new_page()
    page.goto(LIST, wait_until="networkidle")
    try:
        page.wait_for_function(
            "[...document.querySelectorAll('a')].some(a=>a.textContent.trim().toUpperCase()==='REGISTER')",
            timeout=30000,
        )
    except Exception:
        print("TITLE:", page.title())
        print(page.inner_text("body")[:1500])
        sys.exit("tournament list not found")
    rows = page.evaluate(LIST_JS)
    print("tournaments:", len(rows))
    if not rows:
        sys.exit("no tournaments found - keeping old data")
    for r in rows:
        m = re.search(r"/p/([A-Za-z0-9]+)", r["url"] or "")
        r["addr"] = ""
        if not m:
            continue
        try:
            page.goto(f"{BASE}/p/{m.group(1)}/t", wait_until="domcontentloaded")
            page.wait_for_function("document.body.innerText.includes('Address')", timeout=15000)
            r["addr"] = page.evaluate(ADDR_JS)
        except Exception as e:
            print("no address:", r["name"], e)
    b.close()

out = []
for r in rows:
    c = country(r["cc"])
    addr = r["addr"] or c
    if r["addr"] and c and c.lower() not in addr.lower():
        addr += ", " + c
    g = loose(addr) or {}
    out.append({"name": r["name"], "addr": addr, "date": r["date"], **g})
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))

OUT.write_text(json.dumps({"updated": datetime.datetime.utcnow().isoformat() + "Z", "tournaments": out}, ensure_ascii=False, indent=1))
print("saved", len(out))
