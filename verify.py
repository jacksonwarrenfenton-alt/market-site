from playwright.sync_api import sync_playwright
import json, os
CH="/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
if not os.path.exists(CH):
    import glob; c=glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome"); CH=c[0] if c else None
print("chromium:", CH)
out={}
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=CH, args=["--no-sandbox"])
    pg=b.new_page(viewport={"width":1500,"height":1000})
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    cons=[]; pg.on("console", lambda m: cons.append(m.type+":"+m.text) if m.type=="error" else None)
    pg.goto("file:///root/pos/market_site.html", wait_until="load", timeout=120000)
    pg.wait_for_timeout(2500)
    out["tabs"]=pg.eval_on_selector_all(".tab","els=>els.map(e=>e.textContent)")
    out["cot_charts"]=pg.eval_on_selector_all("[data-c][data-has]","e=>e.length")
    out["flow_charts"]=pg.eval_on_selector_all("[data-f][data-has]","e=>e.length")
    # new baskets present in the flow table?
    out["new_baskets"]=pg.eval_on_selector_all(
        "[data-f]","els=>els.map(e=>e.dataset.f).filter(x=>x.indexOf('Index ')===0)")
    pg.screenshot(path="/root/pos/shot_pos.png", full_page=False)

    # --- PATCH D: open from a RANKED SIGNAL ROW (has data-ctx) ---
    row=pg.query_selector('table.sig td.nm[data-c][data-ctx][data-has]')
    out["signal_row"]=row.get_attribute("data-ctx") if row else None
    if row:
        row.click(); pg.wait_for_timeout(1200)
        out["arrows_btn"]=pg.eval_on_selector_all('.tg[data-p="arrows"]',"e=>e.length")
        out["arrows_on"]=pg.eval_on_selector_all('.tg[data-p="arrows"].on',"e=>e.length")
        out["primary"]=pg.evaluate("document.getElementById('ovc')._spec.primary")
        out["panes_open"]=pg.eval_on_selector_all(".pane","e=>e.map(x=>x.dataset.pane)")
        out["tri_price_single"]=pg.eval_on_selector_all(
            '.pane[data-pane="price"] svg path[fill-opacity="0.95"]',"e=>e.length")
        # turn arrows OFF
        pg.click('.tg[data-p="arrows"]'); pg.wait_for_timeout(800)
        out["tri_after_off"]=pg.eval_on_selector_all(
            '.pane[data-pane="price"] svg path[fill-opacity="0.95"]',"e=>e.length")
        pg.screenshot(path="/root/pos/shot_modal.png")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(400)

    # --- open a COMMERCIAL row: must show exactly 3 panes ---
    c=pg.query_selector('[data-ctx="comm"][data-has]')
    if c:
        c.click(); pg.wait_for_timeout(1200)
        out["comm_panes"]=pg.eval_on_selector_all(".pane","e=>e.map(x=>x.dataset.pane)")
        out["comm_primary"]=pg.evaluate("document.getElementById('ovc')._spec.primary")
        # zoom brush drag
        lab=pg.eval_on_selector(".pzlab","e=>e.textContent")
        bar=pg.query_selector(".pzwin"); bb=bar.bounding_box()
        pg.mouse.move(bb["x"]+bb["width"]/2, bb["y"]+bb["height"]/2); pg.mouse.down()
        pg.mouse.move(bb["x"]+bb["width"]/2-180, bb["y"]+bb["height"]/2, steps=8); pg.mouse.up()
        pg.wait_for_timeout(600)
        out["brush"]=[lab, pg.eval_on_selector(".pzlab","e=>e.textContent")]
        pg.keyboard.press("Escape"); pg.wait_for_timeout(400)

    # --- open from a TILE (no data-ctx): arrows must default OFF ---
    t=pg.query_selector('.tile .tv[data-c][data-has]')
    if t:
        t.click(); pg.wait_for_timeout(1200)
        out["tile_primary"]=pg.evaluate("document.getElementById('ovc')._spec.primary")
        out["tile_arrows_on"]=pg.eval_on_selector_all('.tg[data-p="arrows"].on',"e=>e.length")
        out["tile_tri"]=pg.eval_on_selector_all(
            '.pane[data-pane="price"] svg path[fill-opacity="0.95"]',"e=>e.length")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(400)

    # --- flow chart for the new short basket ---
    f=pg.query_selector('[data-f="Index Short (inverse)"][data-has]')
    if f:
        f.click(); pg.wait_for_timeout(1500)
        out["short_basket_panes"]=pg.eval_on_selector_all(".pane","e=>e.map(x=>x.dataset.pane)")
        out["short_basket_sub"]=pg.eval_on_selector(".chs","e=>e.textContent")
        pg.screenshot(path="/root/pos/shot_flow.png")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(400)

    for i,t2 in enumerate(["p-sub","p-diary"]):
        pg.eval_on_selector(f'.tab[data-pane="{t2}"]',"e=>e.click()"); pg.wait_for_timeout(1200)
        pg.screenshot(path=f"/root/pos/shot_{t2}.png", full_page=False)
    out["errors"]=errs[:5]; out["console_errors"]=cons[:5]
    b.close()
print(json.dumps(out, indent=1))
