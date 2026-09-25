from playwright.sync_api import sync_playwright
import glob
CH=glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome")[0]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=CH,args=["--no-sandbox"])
    pg=b.new_page(viewport={"width":1500,"height":1400})
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///root/pos/market_site.html", wait_until="load", timeout=120000)
    pg.wait_for_timeout(2500)
    pg.eval_on_selector('.tab[data-pane="p-diary"]',"e=>e.click()"); pg.wait_for_timeout(1500)
    el=pg.query_selector('.sbbox')
    el.scroll_into_view_if_needed(); pg.wait_for_timeout(400)
    pg.screenshot(path="/root/pos/shot_sb.png", clip={"x":0,"y":max(0,el.bounding_box()["y"]-10),"width":1500,"height":900})
    # SI chart
    si=pg.query_selector('.mcbox')
    print("errors:",errs[:3])
    b.close()
