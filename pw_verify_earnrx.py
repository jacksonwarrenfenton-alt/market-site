import sys
from playwright.sync_api import sync_playwright

URL = "file:///root/pos/market_site.html"
results = []

def check(name, cond, extra=""):
    ok = bool(cond)
    results.append((name, ok, extra))
    print(("PASS" if ok else "FAIL"), "-", name, ("(" + extra + ")" if extra else ""))

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.goto(URL, wait_until="load", timeout=60000)
    page.wait_for_timeout(800)

    page.click('button.tab[data-pane="p-diary"]')
    page.wait_for_timeout(300)
    diary_text = page.evaluate("document.getElementById('p-diary').textContent")
    check("Earnings-reaction panel present", "Earnings-reaction breadth" in diary_text)
    check("Panel says ROLLING quarter (not calendar)", "rolling" in diary_text.lower() and "91 days" in diary_text)
    check("Panel explains no reset at quarter boundary", "never resets" in diary_text)

    n_svg = page.locator("#erx-chart svg.mcs").count()
    check("Interactive chart mounted (svg rendered)", n_svg > 0)
    n_series_legend = page.locator("#erx-chart .mclg .k").count()
    check("Chart shows one legend swatch per sector", n_series_legend >= 5, f"{n_series_legend} sectors")

    # zoom-brush interactivity check: the window starts at full range [0,1],
    # where the .hr handle sits right at the bar's own right edge -- drag
    # THAT handle inward (not the window body, which just re-clamps back to
    # full range at the edge) to actually shrink the visible window, then
    # confirm the rendered date-range label changed.
    page.locator("#erx-chart").scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    before = page.locator("#erx-chart .tflab").inner_text()
    handle = page.locator("#erx-chart i.hr")
    bar = page.locator("#erx-chart .tfbar")
    hbox, bbox = handle.bounding_box(), bar.bounding_box()
    if hbox and bbox:
        page.mouse.move(hbox["x"] + hbox["width"] / 2, hbox["y"] + hbox["height"] / 2)
        page.mouse.down()
        # Discrete move() calls, not one steps= call -- the brush listens on
        # real pointermove events and a single interpolated Playwright move
        # doesn't reliably dispatch the intermediate ones.
        for i in range(1, 9):
            frac = 1 - i / 8 * 0.4
            page.mouse.move(bbox["x"] + bbox["width"] * frac, hbox["y"] + hbox["height"] / 2)
        page.mouse.up()
        page.wait_for_timeout(200)
    after = page.locator("#erx-chart .tflab").inner_text()
    check("Drag-to-zoom brush changes the visible date window", before != after,
          f"before={before!r} after={after!r}")

    # mode toggle check
    page.locator('#erx-chart .mcm[data-m="log"]').click()
    page.wait_for_timeout(150)
    on_cls = page.get_attribute('#erx-chart .mcm[data-m="log"]', "class") or ""
    check("Mode toggle (Index/Log/Raw) responds to click", "on" in on_cls)

    rows = page.locator('#p-diary table.sig.sortable tr').count()
    check("Sector breadth table has rows", rows > 1, f"{rows} rows incl header")

    browser.close()

n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"\n{len(results)-n_fail}/{len(results)} checks passed")
sys.exit(1 if n_fail else 0)
