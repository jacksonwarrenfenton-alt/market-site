"""liqn.ai capture from the cloud, signed in with jman's own session cookie.

liqn.ai's crowd board and homepage both sit behind "Continue with Google / X".
Those OAuth providers block automated sign-ins from cloud browsers (and would
trip 2FA / suspicious-login checks on the account), so this never logs in.
Instead it reuses a session jman already has: he copies liqn.ai's cookie header
from his signed-in Chrome into the cloud environment as the secret
LIQN_COOKIE, and this loads it into headless Chromium.

  LIQN_COOKIE   the full `cookie:` request header value for liqn.ai, e.g.
                "name1=value1; name2=value2" (DevTools > Network > any liqn.ai
                request > Request Headers > cookie). Never commit it, never
                paste it into chat; it is an environment secret only.

When the variable is missing this is a no-op. When the cookie has expired the
site bounces to its landing page; that is detected, nothing is appended, and
the log says to refresh the cookie -- the crowd panels then fall back to the
login-free feed (crowdfeed.py) as before.

The crowd board goes through liqn.parse/append -> liqn_hist.csv, identical to
the Mac capture. liqnnews.py has no parser yet, so the homepage text is saved
to liqnnews_page.txt until one is written from a real signed-in capture.
"""
import os, sys

CROWD_URL = "https://liqn.ai/analysis/crowd"
HOME_URL = "https://liqn.ai/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def _log(msg):
    print(f"liqncloud: {msg}", file=sys.stderr, flush=True)


def _cookies(header):
    out = []
    for part in header.split(";"):
        if "=" not in part: continue
        k, v = part.strip().split("=", 1)
        if k:
            out.append({"name": k, "value": v, "domain": "liqn.ai", "path": "/",
                        "secure": True, "sameSite": "Lax"})
    return out


def _text(pg, url, must, tries=4):
    pg.goto(url, timeout=60000, wait_until="domcontentloaded")
    for _ in range(tries):
        pg.wait_for_timeout(4000)
        if "/landing" in pg.url:
            return None, "expired"
        t = pg.inner_text("body")
        if all(m.lower() in t.lower() for m in must):
            return t, "ok"
    return None, "not rendered"


def run():
    header = os.environ.get("LIQN_COOKIE", "").strip()
    if not header:
        _log("LIQN_COOKIE not set -- skipped (crowd panels use the login-free feed)")
        return {"crowd": "skipped", "news": "skipped"}
    from playwright.sync_api import sync_playwright
    from etfdbflows import trust_proxy_ca, _chromium
    import liqn, liqnnews
    trust_proxy_ca()
    res = {}
    with sync_playwright() as p:
        kw = {"args": ["--disable-blink-features=AutomationControlled"]}
        if _chromium(): kw["executable_path"] = _chromium()
        b = p.chromium.launch(**kw)
        ctx = b.new_context(user_agent=UA, viewport={"width": 1680, "height": 1050})
        ctx.add_cookies(_cookies(header))
        pg = ctx.new_page()

        t, st = _text(pg, CROWD_URL, ["of all crowd chatter"])
        if t:
            row = liqn.parse(t)
            d = liqn.append(row)
            res["crowd"] = f"ok -- {len(d)} rows, top-10 {row.get('top10_share')}%"
        else:
            res["crowd"] = st
        if st == "expired":
            _log("liqn.ai session EXPIRED -- refresh LIQN_COOKIE from a signed-in Chrome")
        else:
            t, st2 = _text(pg, HOME_URL, ["top stories"])
            if t and not hasattr(liqnnews, "parse"):
                # liqnnews.py only renders today; no parser has been written
                # (the Mac task's parse/append calls never existed in git).
                # Keep the signed-in page text so one can be built from it.
                open(os.path.join(liqnnews.D, "liqnnews_page.txt"), "w").write(t)
                res["news"] = "page captured to liqnnews_page.txt -- parser not built yet"
            elif t:
                rows = liqnnews.parse(t)
                if rows:
                    d = liqnnews.append(rows, text_for_date=t)
                    res["news"] = f"ok -- {len(rows)} stories, {len(d)} rows"
                else:
                    res["news"] = "parsed 0 stories"
            else:
                res["news"] = st2
        b.close()
    _log(str(res))
    return res


if __name__ == "__main__":
    run()
