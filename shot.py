from playwright.sync_api import sync_playwright
import sys
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    pg=b.new_page(viewport={"width":1400,"height":1000})
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console:"+m.text) if m.type=="error" else None)
    pg.goto("file:///root/pos/market_site.html"); pg.wait_for_timeout(2500)
    pg.click('button.tab[data-pane="p-diary"]') if pg.query_selector('button.tab[data-pane="p-diary"]') else None
    pg.wait_for_timeout(800)
    el=pg.query_selector(".sbex")
    if el:
        el.scroll_into_view_if_needed(); pg.wait_for_timeout(400)
        print("chips:", len(pg.query_selector_all(".sbchip")))
        print("active chip:", pg.eval_on_selector(".sbchip.on","e=>e.textContent") if pg.query_selector(".sbchip.on") else None)
        print("svg present:", bool(pg.query_selector("#sbchart svg")))
        print("hits text:", pg.eval_on_selector("#sbhits","e=>e.textContent"))
        pg.eval_on_selector("#sbpct","e=>{e.value=97;e.dispatchEvent(new Event('input'))}")
        pg.wait_for_timeout(300)
        print("after slider 97:", pg.eval_on_selector("#sbhits","e=>e.textContent"))
        cs=pg.query_selector_all(".sbchip")
        cs[1].click(); pg.wait_for_timeout(300)
        print("after 2nd chip:", pg.eval_on_selector("#sbhits","e=>e.textContent"))
        pg.click("#sbdir"); pg.wait_for_timeout(300)
        print("lower tail:", pg.eval_on_selector("#sbhits","e=>e.textContent"),
              "|", pg.eval_on_selector("#sbdir","e=>e.textContent"))
        el.screenshot(path="/root/pos/shot_sbex.png")
    else: print("NO .sbex found")
    si=pg.query_selector("#sichart")
    if si:
        si.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
        print("si svg:", bool(pg.query_selector("#sichart svg")),
              "| bars:", len(pg.query_selector_all("#sichart rect")))
        si.screenshot(path="/root/pos/shot_si.png")
    print("ERRORS:", errs[:6] if errs else "none")
    b.close()
