"""Browser-level check for the two-photo crosscheck UI.

Seeds two differently lit panels through the library, opens GrooveDesk in
headless Chromium and verifies: companion selection, launching a check from a
surface mark row, the verdict narrative, A/B switching and evidence segment
location while the original surface mark stays untouched.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from groovedesk import photo
from groovedesk.store import Library
from scripts.dev_crosscheck_test import make_pair, settings

DATA_ROOT = "/tmp/groovedesk-browser-test"
URL = "http://127.0.0.1:19899/"


def seed():
    import shutil
    shutil.rmtree(DATA_ROOT, ignore_errors=True)
    library = Library(DATA_ROOT + "/inspection")
    image_a, image_b, box = make_pair("joint")
    chosen = settings("S-1", box)
    panel_a = library.create("joint-A", "a.png", photo.png(image_a), image_a.size, chosen, {"kind": "synthetic"})
    panel_b = library.create("joint-B", "b.png", photo.png(image_b), image_b.size, chosen, {"kind": "synthetic"})
    panel_a = library.pair(panel_a["id"], panel_b["id"])
    # A second single-sided pair for the verdict switching check.
    image_c, image_d, box2 = make_pair("single")
    chosen2 = settings("S-1", box2)
    panel_c = library.create("single-A", "c.png", photo.png(image_c), image_c.size, chosen2, {"kind": "synthetic"})
    panel_d = library.create("single-B", "d.png", photo.png(image_d), image_d.size, chosen2, {"kind": "synthetic"})
    library.pair(panel_c["id"], panel_d["id"])
    return panel_a["id"], panel_c["id"]


def click_library(page, title):
    texts = page.locator("#library button").all_inner_texts()
    button = page.locator("#library button").nth(texts.index(title))
    # Clicks can land while a prior async inspection holds the JS busy lock;
    # retry until the workspace title actually switches.
    for _ in range(5):
        button.click()
        try:
            page.wait_for_function(
                f"document.getElementById('title').textContent.includes({json.dumps(title)})", timeout=4000)
            return
        except Exception:
            page.wait_for_timeout(500)
    raise AssertionError(f"failed to open panel {title}")


def main():
    # Seeding happens before the server starts; rerun seed() from a separate
    # process and restart the server rather than deleting its live data root.
    panel_a, panel_c = (None, None)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/opt/pointwise-env/browsers/chromium_headless_shell-1255/"
            "chrome-headless-shell-linux64/chrome-headless-shell",
            args=["--no-sandbox"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(URL)
        page.wait_for_selector("#library button")
        page.wait_for_load_state("networkidle")
        # The page auto-opens the newest panel under a JS busy lock; wait for
        # that first inspection to finish before issuing any clicks.
        page.wait_for_selector("#result-rows tr", timeout=15000)
        page.wait_for_function("document.getElementById('status').textContent.includes('已打开原片')")
        # open the joint pair panel explicitly regardless of auto-selection
        click_library(page, "joint-A")
        page.wait_for_function(
            "document.getElementById('title').textContent.includes('joint-A')")
        page.wait_for_selector("#result-rows tr")
        # companion select should show joint-B selected
        page.wait_for_function("document.getElementById('companion').value !== ''")
        companion_title = page.locator("#companion option:checked").inner_text()
        assert "joint-B" in companion_title, companion_title
        # launch crosscheck from the surface mark row button
        page.wait_for_load_state("networkidle")
        page.locator("#result-rows tr button:has-text('双片核对')").first.click()
        page.wait_for_selector("#cross-narrative:not([hidden])", timeout=15000)
        verdict = page.locator("#cross-verdict").inner_text()
        assert verdict == "同位证据", verdict
        narrative = page.locator("#cross-default").inner_text()
        assert "默认读法" in narrative and "共同证据" in narrative, narrative
        # evidence rows exist and the joint segment is selected by default
        rows = page.locator("#result-rows tr")
        assert rows.count() >= 1
        selected = page.locator("#result-rows tr.selected")
        assert selected.count() == 1
        # the photo SVG shows evidence polygons in both views
        def polygon_count():
            return page.locator("#photo path[d^='M ']").count()
        before = polygon_count()
        assert before >= 1
        # switch to B: image source must change to the companion panel
        img_href = page.locator("#photo image").first.get_attribute("href")
        page.click("#view-b")
        page.wait_for_function(
            f"document.querySelector('#photo image').getAttribute('href') !== {json.dumps(img_href)}")
        b_href = page.locator("#photo image").first.get_attribute("href")
        assert "/panels/" in b_href and b_href != img_href
        # evidence polygon still present in B and selection survives
        assert polygon_count() >= 1
        assert page.locator("#result-rows tr.selected").count() == 1
        # clicking another evidence row relocates the crosshair in B
        page.locator("#result-rows tr").first.click()
        page.wait_for_selector("#photo path[d*='V']")
        # back to surface: mark remains, selection restored
        page.click("#back-surface")
        page.wait_for_selector("#cross-narrative", state="hidden")
        assert page.locator("#result-rows tr").count() == 1
        assert page.locator("#result-rows tr.selected").count() == 1
        # open the single-sided panel and verify verdict
        click_library(page, "single-A")
        page.wait_for_function(
            "document.getElementById('title').textContent.includes('single-A')")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("#result-rows tr")
        page.wait_for_load_state("networkidle")
        page.locator("#result-rows tr button:has-text('双片核对')").first.click()
        page.wait_for_selector("#cross-narrative:not([hidden])", timeout=15000)
        assert page.locator("#cross-verdict").inner_text() == "主要见于一张"
        assert "单方证据" in page.locator("#cross-default").inner_text()
        # save the check and reopen it
        page.click("#save")
        page.wait_for_selector("#downloads:not([hidden])")
        page.reload()
        page.wait_for_selector("#archive button")
        page.click("#archive button")
        page.wait_for_selector("#cross-narrative:not([hidden])")
        assert page.locator("#cross-verdict").inner_text() == "主要见于一张"
        # A/B switching still works after reopening saved check
        href_a = page.locator("#photo image").first.get_attribute("href")
        page.click("#view-b")
        page.wait_for_function(
            f"document.querySelector('#photo image').getAttribute('href') !== {json.dumps(href_a)}")
        assert not any("Failed to load resource" in e for e in errors), errors
        browser.close()
    assert not errors, [e for e in errors if "favicon" not in e.lower()]
    print("browser crosscheck UI assertions passed")


if __name__ == "__main__":
    main()
