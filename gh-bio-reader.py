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
        for ua in BOT_UAS + [UA]:
            try:
                html = get(
                    f"https://www.instagram.com/{handle}/",
                    headers=dict(HEADERS, **{"User-Agent": ua}),
                )
                parsed = parse_profile(html)
                row.update(parsed)
                row["len"] = len(html)
                row["ua"] = ua[:30]
                # the login-wall page has a welcome-text description meta but
                # no numeric id; only a page with the id is a real profile
                if row.get("owner_id"):
                    break
            except Exception as e:
                row["error"] = f"{type(e).__name__}: {str(e)[:100]}"
        print(json.dumps(row)[:400])
        if row.get("owner_id"):
            report(row)
    return 0


sys.exit(main())
