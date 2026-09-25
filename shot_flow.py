from playwright.sync_api import sync_playwright
import glob
CH=glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome")[0]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=CH,args=["--no-sandbox"])
    pg=b.new_page(viewport={"width":1200,"height":1100})
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///root/pos/market_site.html", wait_until="load", timeout=120000)
    pg.wait_for_timeout(2500)
    el=pg.query_selector('[data-f="Index Short (inverse)"][data-has]')
    el.click(); pg.wait_for_timeout(1800)
    print("panes:", pg.eval_on_selector_all(".pane","e=>e.map(x=>x.dataset.pane)"))
    print("price lab:", pg.eval_on_selector('.pane[data-pane="price"] svg text',"e=>e.textContent"))
    print("x tick labels:", pg.eval_on_selector_all(
        '.pane[data-pane="flow"] svg text',"e=>e.map(t=>t.textContent).filter(s=>/^[A-Z][a-z]{2} \\d{2}$/.test(s))"))
    # hover to trigger crosshair
    box=pg.query_selector('.pzbody').bounding_box()
    pg.mouse.move(box["x"]+box["width"]*0.55, box["y"]+120); pg.wait_for_timeout(600)
    print("crosshair groups visible:", pg.eval_on_selector_all(
        'g.xh',"e=>e.filter(g=>g.style.display!=='none').length"),"of",
        pg.eval_on_selector_all('g.xh',"e=>e.length"))
    print("date readout:", pg.eval_on_selector('.pzdate',"e=>e.textContent"))
    pg.screenshot(path="/root/pos/shot_xh.png", clip={"x":box["x"]-20,"y":box["y"]-90,"width":900,"height":700})
    print("errors:", errs[:3])
    b.close()
