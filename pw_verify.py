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

    # ---- go to Market Diary tab ----
    page.click('button.tab[data-pane="p-diary"]')
    page.wait_for_timeout(300)
    diary_visible = page.is_visible("#p-diary")
    check("Market diary tab activates", diary_visible)

    # confirm the moved panels are gone from diary and new one is present
    diary_text = page.evaluate("document.getElementById('p-diary').textContent")
    check("Market diary has NO 'Google Trends' panel", "Google Trends" not in diary_text)
    check("Market diary HAS earnings-reaction breadth panel", "Earnings-reaction breadth" in diary_text)

    # ---- click a static etfsi.py [data-e] ticker cell ----
    etf_cell = page.locator('#p-diary td.nm[data-e]').first
    etf_sym = etf_cell.get_attribute("data-e")
    etf_cell.scroll_into_view_if_needed()
    etf_cell.click()
    page.wait_for_timeout(500)
    ov_on = "on" in (page.get_attribute("#ov", "class") or "")
    check(f"Clicking static ETF row ({etf_sym}) opens overlay", ov_on)
    ovc_html = page.inner_html("#ovc")
    check("Combined chart shows ticker name", etf_sym in ovc_html)
    has_price_pane = "PRICE" in ovc_html or "Price" in ovc_html
    check("Combined chart has a price-related pane label", has_price_pane)
    # close overlay
    if page.locator("#ov .ovx, #ov .close, #ov [data-close]").count() > 0:
        page.locator("#ov .ovx, #ov .close, #ov [data-close]").first.click()
    else:
        page.evaluate("document.getElementById('ov').classList.remove('on')")
    page.wait_for_timeout(300)

    # ---- click a flow basket [data-f] (lives on the Positioning tab) ----
    page.click('button.tab[data-pane="p-pos"]')
    page.wait_for_timeout(400)
    basket_cell = page.locator('#p-pos td.nm[data-f]').first
    basket_name = basket_cell.get_attribute("data-f")
    basket_cell.scroll_into_view_if_needed()
    basket_cell.click()
    page.wait_for_timeout(500)
    ov_on2 = "on" in (page.get_attribute("#ov", "class") or "")
    check(f"Clicking flow basket ({basket_name}) opens overlay", ov_on2)
    ovc_html2 = page.inner_html("#ovc")
    check("Flow modal shows constituents table", "Constituents" in ovc_html2)

    # ---- click a constituent row inside the now-open modal ----
    constituent = page.locator('#ovc td.nm[data-e]').first
    n_constituents = page.locator('#ovc td.nm[data-e]').count()
    check("Flow modal has clickable constituent rows", n_constituents > 0, f"{n_constituents} rows")
    if n_constituents > 0:
        cons_sym = constituent.get_attribute("data-e")
        constituent.click()
        page.wait_for_timeout(500)
        ovc_html3 = page.inner_html("#ovc")
        check(f"Clicking constituent ({cons_sym}) shows its own combined chart", cons_sym in ovc_html3)
        has_back = page.locator("#ovc .backlink, #ovc [data-back]").count() > 0
        check("Constituent chart shows a 'back to basket' link", has_back)
        if has_back:
            page.locator("#ovc .backlink, #ovc [data-back]").first.click()
            page.wait_for_timeout(500)
            ovc_html4 = page.inner_html("#ovc")
            check("Back link returns to basket flow chart", basket_name in ovc_html4 and "Constituents" in ovc_html4)
    page.evaluate("document.getElementById('ov').classList.remove('on')")
    page.wait_for_timeout(300)

    # ---- Global & liquidity: now the 4th AI-desk sub-tab, not a top-level tab ----
    check("Global is no longer a top-level tab",
          page.locator('button.tab[data-pane="p-global"]').count() == 0)
    page.click('button.tab[data-pane="p-ai"]')
    page.wait_for_timeout(400)
    gl_btn = page.locator('#p-ai button.aitab[data-p="p-gl"]')
    check("AI desk has 'Global & liquidity' sub-tab button", gl_btn.count() > 0)
    if gl_btn.count() > 0:
        gl_btn.first.click()
        page.wait_for_timeout(400)
        check("Global & liquidity pane becomes visible on click", page.is_visible("#p-gl"))
        h2s = [h.strip().upper() for h in page.locator("#p-gl h2").all_inner_texts()]
        idxs = {name: (h2s.index(name.upper()) if name.upper() in h2s else -1)
                for name in ("Commodities", "Fed", "VIX", "Sentiment")}
        order_ok = -1 not in idxs.values() and (
            idxs["Commodities"] < idxs["Fed"] < idxs["VIX"] < idxs["Sentiment"])
        check("Global sections in order Commodities->Fed->VIX->Sentiment", order_ok,
              f"{idxs} (all h2s: {h2s})")
        check("Fed Watch cards render", page.locator("#p-gl .fwgrid .fwcard").count() > 0,
              f"{page.locator('#p-gl .fwgrid .fwcard').count()} cards")

    # ---- AI desk tab -> Regime & positioning sub-tab ----
    page.click('button.tab[data-pane="p-ai"]')
    page.wait_for_timeout(400)
    regime_btn = page.locator('#p-ai button.aitab[data-p="p-regime"]')
    check("AI desk has 'Regime & positioning' sub-tab button", regime_btn.count() > 0)
    regime_btn.first.click()
    page.wait_for_timeout(400)
    regime_pane_visible = page.is_visible("#p-regime")
    check("Regime & positioning pane becomes visible on click", regime_pane_visible)
    regime_text = page.evaluate("document.getElementById('p-regime').textContent")
    check("Regime pane shows allocation tiles (Equity/Bonds/Commodities/Cash)",
          all(w in regime_text for w in ["Equity", "Commodities", "Cash"]))
    check("Regime pane shows positioning-unwind watch section",
          "Positioning-unwind watch" in regime_text)

    browser.close()

n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"\n{len(results)-n_fail}/{len(results)} checks passed")
sys.exit(1 if n_fail else 0)

