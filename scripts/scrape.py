import io, json, re, sys, time, datetime, pathlib, unicodedata, urllib.request, urllib.parse
import pycountry
from bs4 import BeautifulSoup
from pypdf import PdfReader
from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
ITSF_URL = "https://tablesoccer.org/tournaments/"
CORAL = "https://app.tablesoccer.org"
WFT_URL = "https://worldfoosballtour.com/pages/wft-tournament-schedule"
P4P_URL = "https://www.players4players.de/en/tournaments"
S_ITSF, S_WFT, S_P4P = "ITSF", "World Foosball Tour", "P4P"
OUT = pathlib.Path("data/tournaments.json")
CACHE = pathlib.Path("data/geocache.json")
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
MON3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


# ---------- pomocne funkce ----------
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=40).read()


def country_name(cc):
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
        print("geocode fail", q, e)
        return None
    cache[q] = {"lat": float(j[0]["lat"]), "lon": float(j[0]["lon"])} if j else None
    return cache[q]


def loose(addr):
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    for k in range(len(parts)):
        g = geocode(", ".join(parts[k:]))
        if g:
            return {**g, "approx": k > 0}
    return None


def hav(a, b):
    import math
    r = math.pi / 180
    dl, dn = (b[0] - a[0]) * r, (b[1] - a[1]) * r
    x = math.sin(dl / 2) ** 2 + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(dn / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


MON_RE = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"


def to_range(s):
    """'23 - 25 Oct', '15 - 18 Oct 2026', '29 Jul - 1 Aug 2027', '5 Dec' -> (start, end) jako date, jinak None"""
    try:
        today = datetime.date.today()
        ym = re.search(r"\b(20\d\d)\b", s)
        m = re.search(r"(?<!\d)(\d{1,2})\s*" + MON_RE + r"?[a-z]*\s*[-\u2013]\s*(\d{1,2})\s*" + MON_RE, s, re.I)
        if m:
            d1, d2 = int(m.group(1)), int(m.group(3))
            m2 = MON3.index(m.group(4).capitalize())
            m1 = MON3.index(m.group(2).capitalize()) if m.group(2) else m2
        else:
            m = re.search(r"(?<!\d)(\d{1,2})\s*" + MON_RE, s, re.I)
            if not m:
                return None
            d1 = d2 = int(m.group(1))
            m1 = m2 = MON3.index(m.group(2).capitalize())
        y = int(ym.group(1)) if ym else today.year
        a = datetime.date(y, m1 + 1, d1)
        b = datetime.date(y + (1 if m2 < m1 else 0), m2 + 1, d2)
        if not ym and b < today - datetime.timedelta(days=14):
            a = a.replace(year=a.year + 1)
            b = b.replace(year=b.year + 1)
        return a, b
    except Exception:
        return None


# ---------- ITSF ----------
LIST_JS = r"""() => {
 const txt=a=>a.textContent.trim().toUpperCase();
 const regs=[...document.querySelectorAll('a')].filter(a=>txt(a)==='REGISTER');
 const rowOf=a=>{let e=a;while(e.parentElement&&[...e.parentElement.querySelectorAll('a')].filter(x=>txt(x)==='REGISTER').length<2)e=e.parentElement;return e;};
 const dateRe=/^\d{1,2}(\s*-\s*\d{1,2})?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(\s|$)/i;
 return regs.map(a=>{
  const L=rowOf(a).innerText.split('\n').map(x=>x.trim()).filter(Boolean).filter(x=>!/^(REGISTER|INFO|NEW)$/i.test(x));
  return {name:L[0],cc:L.find(x=>/^[A-Z]{3}$/.test(x))||L.slice(1).find(x=>!dateRe.test(x)&&!/^itsf/i.test(x))||'',date:L.find(x=>dateRe.test(x))||'',url:a.href};
 });
}"""
ADDR_JS = """() => {
 const L=document.body.innerText.split(/[\\n\\t]+/).map(x=>x.trim()).filter(Boolean);
 const i=L.lastIndexOf('Address');
 const c=L.indexOf('Category');
 const j=L.indexOf('Table',c>=0?c:0);
 let table=j>=0&&L[j+1]?L[j+1]:'';
 if(['Start','End','Timezone','Contact','Address','Status','Info Package'].includes(table))table='';
 return {addr:i>=0&&L[i+1]?L[i+1]:'',table};
}"""


def scrape_itsf(ctx):
    page = ctx.new_page()
    page.goto(ITSF_URL, wait_until="networkidle")
    try:
        page.wait_for_function(
            "[...document.querySelectorAll('a')].some(a=>a.textContent.trim().toUpperCase()==='REGISTER')",
            timeout=30000,
        )
    except Exception:
        print("TITLE:", page.title())
        print(page.inner_text("body")[:1500])
        raise RuntimeError("ITSF: seznam turnaju nenalezen")
    rows = page.evaluate(LIST_JS)
    print("ITSF turnaje:", len(rows))
    items = []
    for r in rows:
        m = re.search(r"/p/([A-Za-z0-9]+)", r["url"] or "")
        addr, table = "", ""
        if m:
            try:
                page.goto(f"{CORAL}/p/{m.group(1)}/t", wait_until="domcontentloaded")
                page.wait_for_function("document.body.innerText.includes('Address')", timeout=15000)
                res = page.evaluate(ADDR_JS)
                addr, table = res["addr"], (res["table"] or "").strip()
            except Exception as e:
                print("ITSF bez adresy:", r["name"], e)
        c = country_name(r["cc"])
        exact = bool(addr)
        if not addr:
            addr = c
        elif c and c.lower() not in addr.lower():
            addr += ", " + c
        url = f"{CORAL}/p/{m.group(1)}" if m else ""
        items.append({"name": r["name"], "addr": addr, "exact": exact, "date": r["date"], "url": url, "table": table, "source": S_ITSF})
    page.close()
    return items


# ---------- World Foosball Tour ----------
WFT_DATE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?"
    r"(?:\s*[-–]\s*(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+)?(\d{1,2})(?:st|nd|rd|th)?)?,?\s*(\d{4})$",
    re.I,
)
WFT_NOISE = re.compile(r"^(STATE SERIES|WFT MAJOR|MAJOR|-|TBA|[$€]?[\d,.]+ ?[€$]?|Flyer .*)$", re.I)


def parse_wft_lines(lines):
    lines = [l.strip() for l in lines if l.strip()]
    out, seen = [], set()
    for i, line in enumerate(lines):
        m = WFT_DATE.match(line)
        if not m or i + 1 >= len(lines):
            continue
        city = lines[i + 1]
        if re.search(r"tba|flyer", city, re.I):
            continue
        name = ""
        for j in range(i - 1, max(i - 5, -1), -1):
            if not WFT_NOISE.match(lines[j]) and not WFT_DATE.match(lines[j]):
                name = lines[j]
                break
        if not name:
            continue
        mon1 = MON3[MONTHS.index(m.group(1).lower())]
        d1, d2, y = m.group(2), m.group(4), m.group(5)
        if m.group(3) and m.group(3).lower() != m.group(1).lower():
            date = f"{d1} {mon1} - {d2} {MON3[MONTHS.index(m.group(3).lower())]} {y}"
        elif d2:
            date = f"{d1} - {d2} {mon1} {y}"
        else:
            date = f"{d1} {mon1} {y}"
        if re.search(r",\s*[A-Z]{2}$", city):
            city += ", USA"
        key = (name.lower(), date)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "addr": city, "exact": False, "date": date, "table": "", "source": S_WFT})
    return out


def scrape_wft(ctx):
    page = ctx.new_page()
    page.goto(WFT_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    lines = page.inner_text("body").split("\n")
    links = page.evaluate("() => [...document.querySelectorAll('a')].filter(a=>a.href.includes('/pages/')).map(a=>({t:a.innerText,h:a.href.split('?')[0]}))")
    page.close()
    items = parse_wft_lines(lines)
    for it in items:
        it["url"] = next((l["h"] for l in links if it["name"].lower() in l["t"].lower()), WFT_URL)
    print("WFT turnaje:", len(items))
    if not items:
        raise RuntimeError("WFT: zadne turnaje")
    return items


# ---------- P4P ----------
ADDR_RE = re.compile(
    r"(?m)^\s*([A-ZÄÖÜ][\w.\-äöüßÄÖÜ]*(?: [\w.\-äöüßÄÖÜ]+){0,3} \d{1,4}[a-z]?),\s*(\d{4,5})\s+"
    r"([A-ZÄÖÜ][\w.\-/äöüßÄÖÜ]*(?: [A-ZÄÖÜ][\w.\-/äöüßÄÖÜ]*)?)"
)


def pdf_address(url):
    try:
        reader = PdfReader(io.BytesIO(fetch(url)))
        text = "\n".join((reader.pages[i].extract_text() or "") for i in range(min(2, len(reader.pages))))
    except Exception as e:
        print("P4P PDF chyba:", url, e)
        return ""
    return address_from_text(text)


def address_from_text(text):
    m = ADDR_RE.search(text[:4000])
    return f"{m.group(1).strip()}, {m.group(2)} {m.group(3).strip()}" if m else ""


def p4p_date(txt, year):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.\s*-\s*(\d{1,2})\.(\d{1,2})\.", txt)
    if m:
        d1, m1, d2, m2 = (int(x) for x in m.groups())
        if m1 == m2:
            return f"{d1} - {d2} {MON3[m1 - 1]} {year}"
        return f"{d1} {MON3[m1 - 1]} - {d2} {MON3[m2 - 1]} {year}"
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.", txt)
    if m:
        return f"{int(m.group(1))} {MON3[int(m.group(2)) - 1]} {year}"
    return ""


def parse_p4p(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for h2 in soup.find_all("h2"):
        ym = re.search(r"(20\d\d)", h2.get_text())
        table = h2.find_next("table") if ym else None
        if not table:
            continue
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            date = p4p_date(tds[0].get_text(" ", strip=True), ym.group(1))
            name = tds[2].get_text(" ", strip=True)
            loc = tds[3].get_text(" ", strip=True)
            if not date or not name or not loc or re.search(r"nicht|leider|steht", loc, re.I):
                continue
            pdf = ""
            if len(tds) > 4:
                for a in tds[4].find_all("a"):
                    if "ausschreibung" in a.get_text().lower() and a.get("href"):
                        pdf = urllib.parse.urljoin(P4P_URL, a["href"])
            out.append({"name": name, "loc": loc.replace(" - ", ", "), "date": date, "pdf": pdf})
    return out


def scrape_p4p():
    rows = parse_p4p(fetch(P4P_URL))
    today = datetime.date.today()
    items = []
    for r in rows:
        rng = to_range(r["date"])
        if rng and rng[1] < today:
            continue
        addr = pdf_address(r["pdf"]) if r["pdf"].lower().endswith(".pdf") else ""
        items.append({"name": r["name"], "addr": addr or r["loc"], "exact": bool(addr), "date": r["date"],
                      "url": P4P_URL, "table": "", "source": S_P4P})
    print("P4P turnaje:", len(items), "s adresou z PDF:", sum(1 for i in items if i["exact"]))
    if not items:
        raise RuntimeError("P4P: zadne turnaje")
    return items


def name_tokens(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    toks = re.findall(r"[a-z0-9]+", n)
    return {t for t in toks if t != "itsf" and not re.search(r"\d", t)}


def same_name(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    inter = ta & tb
    return len(inter) >= 2 and len(inter) / min(len(ta), len(tb)) >= 0.8


def merge(out):
    """Slouci duplicity. Stejny turnaj = podobny nazev (po odstraneni roku, cisel a slova ITSF)
    a zaroven zacatek v rozmezi 3 dnu, nebo stejny zacatek a vzdalenost do 40 km.
    Priorita zdroju pri konfliktu: ITSF > World Foosball Tour > P4P. Vitezny zaznam si ponecha vsechna data,
    ostatni zdroje se jen pripisou do 'sources'."""
    merged = []
    for t in out:
        rng = to_range(t["date"])
        dup = None
        if rng:
            for m in merged:
                mr = to_range(m["date"])
                if not mr:
                    continue
                days = abs((mr[0] - rng[0]).days)
                near = (m.get("lat") is not None and t.get("lat") is not None
                        and hav((m["lat"], m["lon"]), (t["lat"], t["lon"])) < 40)
                if (days <= 3 and same_name(m["name"], t["name"])) or (days == 0 and near):
                    dup = m
                    break
        if dup:
            for src in t["sources"]:
                if src not in dup["sources"]:
                    dup["sources"].append(src)
        else:
            merged.append(t)
    return merged


# ---------- hlavni beh ----------
def main():
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    old_items = old.get("tournaments", [])
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 900}, locale="en-US", user_agent=UA)
        for key, fn in ((S_ITSF, scrape_itsf), (S_WFT, scrape_wft)):
            try:
                results[key] = fn(ctx)
            except Exception as e:
                print("CHYBA zdroje", key, ":", e)
        b.close()
    try:
        results[S_P4P] = scrape_p4p()
    except Exception as e:
        print("CHYBA zdroje", S_P4P, ":", e)
    if not results:
        sys.exit("zadny zdroj nefunguje - ponechavam stara data")

    # zdroje, ktere selhaly: prevezmu predchozi data
    out = []
    for src in (S_ITSF, S_WFT, S_P4P):
        if src in results:
            items = results[src]
            for it in items:
                g = loose(it["addr"]) if it["exact"] else geocode(it["addr"])
                g = dict(g) if g else {}
                if g:
                    g["approx"] = (not it["exact"]) or bool(g.get("approx"))
                rec = {"name": it["name"], "addr": it["addr"], "date": it["date"], "url": it.get("url", ""),
                       "table": it.get("table", ""), "sources": [src], **g}
                out.append(rec)
                CACHE.write_text(json.dumps(cache, ensure_ascii=False))
        else:
            out += [t for t in old_items if t.get("sources", [S_ITSF]) == [src]]

    merged = merge(out)

    OUT.write_text(json.dumps({"updated": datetime.datetime.utcnow().isoformat() + "Z", "tournaments": merged},
                              ensure_ascii=False, indent=1))
    print("ulozeno", len(merged))


if __name__ == "__main__":
    main()
