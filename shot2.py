from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    pg=b.new_page(viewport={"width":1400,"height":1150})
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///root/pos/market_site.html"); pg.wait_for_timeout(2200)
    pg.click('button.tab[data-pane="p-ai"]'); pg.wait_for_timeout(700)
    print("cards:", len(pg.query_selector_all(".dcard")), "| flags:", len(pg.query_selector_all(".fl")))
    pg.query_selector("#p-ai").screenshot(path="/root/pos/shot_ai.png")
    pg.fill("#tq","NVDA"); pg.click("#tgo"); pg.wait_for_timeout(500)
    print("NVDA cards:", len(pg.query_selector_all(".dcard")),
          "| legs:", len(pg.query_selector_all(".legs2 .lg")))
    pg.click('.aitab[data-p="p-chart"]'); pg.wait_for_timeout(400)
    print("chart pane visible:", not pg.query_selector("#p-chart").get_attribute("hidden"))
    pg.query_selector("#p-ai").screenshot(path="/root/pos/shot_ai2.png")
    print("ERRORS:", errs[:4] if errs else "none")
    b.close()
