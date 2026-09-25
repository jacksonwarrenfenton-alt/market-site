from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    pg=b.new_page(viewport={"width":1400,"height":900})
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///tmp/aitest.html"); pg.wait_for_timeout(1200)
    pg.click('.aitab[data-p="p-chart"]'); pg.wait_for_timeout(600)
    print("opening chart svg:", bool(pg.query_selector("#cout svg")),
          "| paths:", len(pg.query_selector_all("#cout path")))
    print("title:", pg.eval_on_selector(".ctitle","e=>e.textContent") if pg.query_selector(".ctitle") else None)
    pg.click("#cman"); pg.wait_for_timeout(500)
    print("picker chips:", len(pg.query_selector_all("#cslist .sbchip")))
    pg.fill("#cs","gold"); pg.wait_for_timeout(400)
    print("filtered 'gold':", len(pg.query_selector_all("#cslist .sbchip")))
    cs=pg.query_selector_all("#cslist .sbchip")
    if len(cs)>=2:
        cs[0].click(); cs[1].click(); pg.wait_for_timeout(200)
        pg.select_option("#ctr","idx"); pg.click("#cdraw"); pg.wait_for_timeout(500)
        print("after manual draw, paths:", len(pg.query_selector_all("#cout path")))
    pg.query_selector("#p-chart").screenshot(path="/root/pos/shot_cb.png")
    print("ERRORS:", errs[:4] if errs else "none")
    b.close()
