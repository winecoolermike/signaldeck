"""Headless screenshot of the locally served site: python screenshot.py [url]"""
import sys
from playwright.sync_api import sync_playwright
url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765/"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1000, "height": 900}, device_scale_factor=1)
    errs = []; pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(url); pg.wait_for_selector(".card")
    pg.screenshot(path="screenshot.png", full_page=True)
    pg.locator("#card-SPCX").screenshot(path="screenshot_spcx.png")
    pg.locator("#card-VZ .tabs button[data-t='21D']").click()
    pg.locator("#card-VZ").screenshot(path="screenshot_vz_21d.png")
    print("console errors:", errs)
    b.close()
