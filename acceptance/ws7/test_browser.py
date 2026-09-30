"""Real-browser check (F-01): the golden report renders all five charts, with screenshots and the console log.

Needs Playwright and a Chrome/Chromium (WS7_BROWSER_CHANNEL, default "chrome"); skips when unavailable."""

from __future__ import annotations

import os

import pytest

from conftest import BASE, OUT, golden_task, need, save


def test_report_renders_five_charts() -> None:
    need("WS7_BASE_URL")
    golden_task()
    sync_api = pytest.importorskip("playwright.sync_api")
    log: dict = {"console": [], "pageerrors": [], "failed_requests": []}
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel=os.environ.get("WS7_BROWSER_CHANNEL", "chrome") or None, headless=True)
        except Exception as exc:  # no browser installed
            pytest.skip(f"no browser: {exc}")
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("console", lambda m: log["console"].append({"type": m.type, "text": m.text[:400]}))
        page.on("pageerror", lambda e: log["pageerrors"].append(str(e)[:400]))
        page.on("requestfailed", lambda r: log["failed_requests"].append(r.url))
        page.goto(f"{BASE}/", wait_until="networkidle")
        page.locator("select").first.select_option("u_000000000001")  # Alice
        page.get_by_text(golden_task(), exact=True).first.click()  # the golden task, whatever the chat compacted since
        page.get_by_text("SNAP-2026-09-28", exact=False).first.wait_for(timeout=60000)
        page.screenshot(path=str(OUT / "01_task.png"), full_page=True)
        page.get_by_text("Artifacts", exact=True).first.click()
        page.get_by_text("Báo cáo căn A12-08 @ SNAP-2026-09-28").first.click()
        page.wait_for_selector("article.report", timeout=30000)
        page.wait_for_function("document.querySelectorAll('article.report figure.chart .chart-canvas svg').length >= 5", timeout=30000)
        page.wait_for_timeout(1000)
        report = page.locator("article.report")
        report.screenshot(path=str(OUT / "02_report.png"))
        figures = page.locator("article.report figure.chart")
        for i in range(figures.count()):
            figures.nth(i).screenshot(path=str(OUT / f"03_chart_{i + 1}.png"))
        log["figures"] = figures.count()
        log["rendered_svgs"] = page.locator("article.report figure.chart .chart-canvas svg").count()
        log["chart_errors"] = page.locator("article.report .error-text").all_inner_texts()
        log["raw_tokens"] = "{{chart_spec" in report.inner_text()
        browser.close()
    save("browser_log.json", log)
    assert log["figures"] == 5 and log["rendered_svgs"] == 5 and not log["chart_errors"] and not log["raw_tokens"]
    assert not log["pageerrors"]
    noisy = [c for c in log["console"] if c["type"] in {"error", "warning"}]
    assert not noisy, noisy  # F-09: no Vega-Lite version warnings, no render errors
