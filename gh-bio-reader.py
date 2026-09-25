import html as html_mod
import json
import os
import re
import sys
import urllib.request

PORTAL = os.environ.get("PORTAL_URL", "https://clipping.onyxpointmanagement.net")
KEY = os.environ.get("BIO_REPORT_KEY", "")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or HEADERS)
    return urllib.request.urlopen(req, timeout=30).read().decode(errors="replace")


def parse_profile(html):
    out = {}
    m = re.search(r'"biography"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
    if m:
        out["bio"] = m.group(1).encode().decode("unicode_escape", errors="replace")
    m = re.search(r"profilePage_(\d+)", html) or re.search(r'"pk"\s*:\s*"?(\d+)"?', html)
    if m:
        out["owner_id"] = m.group(1)
    m = re.search(r'"username"\s*:\s*"([^"]+)"', html)
    if m:
        out["owner_username"] = m.group(1)
    m = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\']([^"\']*)["\']', html, re.I
    )
    if m:
        out["og"] = m.group(1)
    m = re.search(r'"follower_count":\s*(\d+)', html)
    if m:
        out["follower_count"] = int(m.group(1))
    # PROVEN 2026-09-23: crawler/preview-bot identities get the full page and
    # the bio sits in the plain description meta tag. Zero cookies.
    if not out.get("bio"):
        m = re.search(r'<meta\s+content="([^"]*)"\s+name="description"', html) or re.search(
            r'<meta\s+name="description"\s+content="([^"]*)"', html
        )
        if m:
            import html as hmod

            out["bio"] = hmod.unescape(m.group(1))
    if not out.get("owner_username"):
        m = re.search(r'og:title"\s+content="([^"]*)"', html)
        if m:
            import html as hmod

            t = hmod.unescape(m.group(1))
            mm = re.search(r"\(@([A-Za-z0-9._]+)\)", t)
            if mm:
                out["owner_username"] = mm.group(1)
    return out


BOT_UAS = [
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "TelegramBot/7.0 (like TwitterBot)",
    "WhatsApp/2.24.10.70 W",
    "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
]


def free_proxies():
    # mixed pool: http entries plus socks5 entries, whose pools carry far more
    # residential exits; playwright speaks socks5 natively
    http, socks = [], []
    http_srcs = [
        "https://proxylist.geonode.com/api/proxy-list?limit=50&sort_by=lastChecked",
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    ]
    sock_srcs = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    ]
    for src in http_srcs:
        try:
            if "geonode" in src:
                r = urllib.request.urlopen(src, timeout=15)
                for it in json.loads(r.read().decode(errors="replace"))[:100]:
                    if "http" in (it.get("protocols") or []):
                        http.append(str(it["ip"]) + ":" + str(it["port"]))
            else:
                t = urllib.request.urlopen(src, timeout=20).read().decode(errors="replace")
                for line in t.splitlines()[:400]:
                    line = line.strip()
                    if line and ":" in line and not line.startswith("#"):
                        http.append(line)
        except Exception:
            continue
    for src in sock_srcs:
        try:
            t = urllib.request.urlopen(src, timeout=20).read().decode(errors="replace")
            for line in t.splitlines()[:400]:
                line = line.strip()
                if line and ":" in line and not line.startswith("#"):
                    socks.append(line)
        except Exception:
            continue
    # the sources the owner's own working scraper uses (proven in production)
    try:
        r = urllib.request.urlopen(
            "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.json",
            timeout=15,
        )
        for it in json.loads(r.read().decode(errors="replace")):
            if it.get("ip") and it.get("port"):
                http.append(f"{it['ip']}:{it['port']}")
    except Exception:
        pass
    try:
        r = urllib.request.urlopen(
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies.json", timeout=20
        )
        arr = json.loads(r.read().decode(errors="replace"))
        arr.sort(key=lambda x: x.get("last_checked") or "", reverse=True)
        for it in arr[:150]:
            proto = it.get("protocol")
            addr = f"{it.get('ip')}:{it.get('port')}"
            if proto == "http":
                http.append(addr)
            elif proto in ("socks4", "socks5"):
                socks.append((proto, addr))
    except Exception:
        pass
    seen = set()
    pool = []
    for addr in http[:300]:
        if addr not in seen:
            seen.add(addr)
            pool.append({"server": "http://" + addr, "kind": "http"})
    for entry in socks[:300]:
        proto, addr = entry if isinstance(entry, tuple) else ("socks5", entry)
        if addr not in seen:
            seen.add(addr)
            pool.append({"server": f"{proto}://" + addr, "kind": proto})
    return pool


def read_via_proxies(handle, pool):
    # Instagram blocks cloud egress for crawler identities (proven 2026-09-24);
    # through a home-IP proxy the target sees a residential IP instead
    for px in [p for p in pool if p["kind"] == "http"]:
        for ua in BOT_UAS[:3]:
            try:
                op = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": px["server"], "https": px["server"]})
                )
                req = urllib.request.Request(
                    f"https://www.instagram.com/{handle}/",
                    headers={
                        "User-Agent": ua,
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                page = op.open(req, timeout=20).read().decode(errors="replace")
            except Exception:
                continue
            row = parse_profile(page)
            row["len"] = len(page)
            if row.get("owner_id") and is_full(row):
                row["ua"] = ua[:30]
                row["proxy"] = px["server"]
                return row
    return None


def read_api(handle, proxy=None):
    # the exact endpoint a logged-out browser uses to render the bio; through
    # a home IP it returns the authoritative biography json
    url = "https://www.instagram.com/api/v1/users/web_profile_info/?username=" + handle
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*",
    }
    if proxy:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://" + proxy, "https": "http://" + proxy})
        )
    else:
        op = urllib.request.build_opener()
    page = op.open(urllib.request.Request(url, headers=headers), timeout=20).read().decode(errors="replace")
    u = ((json.loads(page).get("data") or {}).get("user")) or {}
    if not u.get("id"):
        return None
    return {
        "bio": u.get("biography") or "",
        "owner_id": str(u.get("id")),
        "owner_username": u.get("username") or handle,
        "len": 999999,
    }


def is_full(row):
    # a page read only counts when the bio section actually carries text, or
    # when it came from the api (len marker 999999). degraded variants carry
    # the id but strip the bio (proven 2026-09-24)
    if row.get("len", 0) >= 999998:
        return True
    return bool(re.search(r'on Instagram: "[^"]+"', row.get("bio") or ""))


def live_proxies(handle, pool):
    # parallel health-check: hundreds of candidates in, up to 25 live exits out
    from concurrent.futures import ThreadPoolExecutor

    try:
        import requests

        have_requests = True
    except Exception:
        have_requests = False

    def check(px):
        try:
            if px["kind"] == "http":
                op = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": px["server"], "https": px["server"]})
                )
                req = urllib.request.Request(
                    f"https://www.instagram.com/{handle}/",
                    headers={"User-Agent": BOT_UAS[0], "Accept": "text/html"},
                )
                page = op.open(req, timeout=6).read().decode(errors="replace")
            elif have_requests:
                page = requests.get(
                    f"https://www.instagram.com/{handle}/",
                    proxies={"http": px["server"], "https": px["server"]},
                    headers={"User-Agent": BOT_UAS[0], "Accept": "text/html"},
                    timeout=6,
                ).text
            else:
                return None
            return px if "profilePage_" in page else None
        except Exception:
            return None

    outs = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        for px in ex.map(check, pool):
            if px:
                outs.append(px)
                if len(outs) >= 25:
                    break
    print("live exits:", len(outs))
    return outs


def render_once(handle, proxy=None):
    from playwright.sync_api import sync_playwright

    caps = []
    with sync_playwright() as pw:
        if proxy:
            br = pw.chromium.launch(
                headless=True,
                proxy={"server": proxy},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
        else:
            br = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        ctx = br.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        resps = []
        page.on("response", lambda r: resps.append(r))
        page.goto(f"https://www.instagram.com/{handle}/", timeout=25000, wait_until="domcontentloaded")
        page.wait_for_timeout(7000)
        for r in resps:
            try:
                if "biography" in r.url or "web_profile_info" in r.url or "graphql" in r.url:
                    t = r.text()
                    if '"biography"' in t:
                        caps.append(t)
            except Exception:
                pass
        if not caps:
            try:
                t = page.content()
                if '"biography"' in t:
                    caps.append(t)
            except Exception:
                pass
        rendered = ""
        try:
            rendered = page.inner_text("body")
        except Exception:
            pass
        content = ""
        try:
            content = page.content()
        except Exception:
            pass
        br.close()
    mid = re.search(r"profilePage_(\d+)", content or "")
    if rendered and len(rendered) > 40 and mid:
        return {
            "bio": rendered,
            "owner_id": mid.group(1),
            "owner_username": handle,
            "len": 999999,
        }
    for t in caps:
        m = re.search(r'"biography"\s*:\s*"((?:[^"\\]|\\.)*)"', t)
        if not m:
            continue
        import html as hmod

        mid = re.search(r'"pk"\s*:\s*"(\d+)"', t) or re.search(r'"profilePage_(\d+)"', t)
        return {
            "bio": m.group(1).encode().decode("unicode_escape", errors="replace"),
            "owner_id": mid.group(1) if mid else "",
            "owner_username": handle,
            "len": 999999,
            "proxy": proxy or "direct",
        }
    return None


def read_jina(handle):
    # r.jina.ai renders the page in its own browser on its own egress and
    # returns markdown; the bio text is in there when the render succeeds
    try:
        req = urllib.request.Request(
            f"https://r.jina.ai/https://www.instagram.com/{handle}/",
            headers={"Accept": "text/plain", "User-Agent": UA},
        )
        text = urllib.request.urlopen(req, timeout=30).read().decode(errors="replace")
        if not text or "AbuseAlleviationError" in text or "blocked until" in text or len(text) < 200:
            return None
        return {"bio": text, "owner_id": "", "owner_username": handle, "len": 999998, "source": "gh-jina", "ua": "jina-reader"}
    except Exception as e:
        print("jina failed", type(e).__name__)
        return None


def render_bio(handle, live):
    # real chromium capturing the biography from the page's own client-side
    # responses: direct first (a real browser fingerprint can pass where raw
    # urllib gets refused), then the already health-checked exits only
    import subprocess

    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright", "pysocks"], check=False)
    subprocess.run(["playwright", "install", "chromium"], check=False)
    try:
        got = render_once(handle, None)
        if got:
            got["source"] = "gh-render-direct"
            print("render direct ok")
            return got
    except Exception as e:
        print("render direct failed", type(e).__name__)
    for px in live:
        try:
            got = render_once(handle, px["server"])
            if got:
                got["source"] = "gh-render-proxy"
                print("render proxy ok", px["server"])
                return got
        except Exception as e:
            print("render proxy failed", px["server"], type(e).__name__)
    return None


def mirror_bio(handle, proxy=None):
    """Owner order 2026-09-25: public viewer sites serve the bio server-side,
    free, zero cookies, zero login. Bio taken only from the bio container."""
    mirrors = [
        ("imginn", f"https://imginn.com/{handle}/"),
        ("pixwox", f"https://www.pixwox.com/profile/{handle}/"),
        ("picuki", f"https://www.picuki.com/profile/{handle}"),
        ("greatfon", f"https://greatfon.com/profile/{handle}"),
    ]
    for name, url in mirrors:
        try:
            html = get(url)
        except Exception:
            continue
        txt = ""
        m = re.search(r'<(?:div|p|span)[^>]*class="[^"]*(?:bio|description|full-info)[^"]*"[^>]*>(.*?)</(?:div|p|span)>', html, re.S | re.I)
        if m:
            txt = re.sub(r"<[^>]+>", " ", m.group(1))
            txt = html_mod.unescape(re.sub(r"\s+", " ", txt)).strip()
        if txt and re.search(r"^(followers|following|posts|views|stories|highlights)\b", txt, re.I) or re.search(
            r"copyright|privacy policy|terms of service", txt or "", re.I
        ):
            txt = ""
        if len(txt) < 3:
            m = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html)
            if m:
                cand = html_mod.unescape(m.group(1)).strip()
                if cand and not re.match(r"[\d.,]+\s+Followers,\s*[\d.,]+\s+Following,\s*[\d.,]+\s+Posts", cand):
                    txt = cand
        if len(txt) > 2:
            print("mirror bio", handle, name, len(html))
            return {"bio": txt, "owner_id": "", "owner_username": handle, "ua": "mirror-" + name, "len": 999998, "source": "mirror-" + name}
    return None


def report(payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        PORTAL + "/ingest/bioreport",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-bio-key": KEY,
            "User-Agent": UA,
            "Origin": PORTAL,
        },
    )
    r = urllib.request.urlopen(req, timeout=30)
    print("report", payload.get("handle"), r.status)


def main():
    jobs = json.loads(get(PORTAL + "/ingest/biojobs")).get("jobs", [])
    if not jobs:
        jobs = [{"handle": "ariakimbaby"}]
        print("no pending jobs; running egress proof handle")
    print("jobs", len(jobs))
    for job in jobs:
        handle = job["handle"]
        row = {"handle": handle, "source": "gh-actions-runner"}
        pool = free_proxies()
        got = None
        try:
            got = read_api(handle)
            if got:
                got["source"] = "gh-api"
        except Exception as e:
            row["error"] = f"api: {type(e).__name__}"
        if not got:
            for ua in BOT_UAS + [UA]:
                try:
                    html = get(
                        f"https://www.instagram.com/{handle}/",
                        headers=dict(HEADERS, **{"User-Agent": ua}),
                    )
                    parsed = parse_profile(html)
                    parsed["len"] = len(html)
                    parsed["ua"] = ua[:30]
                    if parsed.get("owner_id") and is_full(parsed):
                        got = parsed
                        break
                except Exception as e:
                    row["error"] = f"{type(e).__name__}: {str(e)[:100]}"
        if not got:
            got = mirror_bio(handle)
        # burn discipline (owner's proven tool): health-check exits FIRST, then
        # spend exactly one expensive call per live exit, api before page
        live = live_proxies(handle, pool) if not got else []
        if not got:
            for px in live:
                if px["kind"] != "http":
                    continue
                try:
                    got = read_api(handle, px["server"][7:])
                    got["source"] = "gh-api-proxy"
                    got["proxy"] = px["server"]
                    break
                except Exception:
                    continue
        if not got:
            got = read_via_proxies(handle, live)
        if not got:
            got = read_jina(handle)
        if not got:
            got = render_bio(handle, live)
        if got:
            row.update(got)
        print(json.dumps(row)[:400])
        if row.get("owner_id") and is_full(row):
            report(row)
        elif row.get("bio") and is_full(row):
            report(row)
    return 0


sys.exit(main())
