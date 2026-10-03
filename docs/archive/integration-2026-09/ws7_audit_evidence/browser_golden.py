import json, re, sys, time
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]
Q = "Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo."
log = {"console": [], "pageerrors": [], "failed_requests": []}
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.on("console", lambda m: log["console"].append({"type": m.type, "text": m.text[:300]}))
    page.on("pageerror", lambda e: log["pageerrors"].append(str(e)[:300]))
    page.on("requestfailed", lambda r: log["failed_requests"].append(r.url))
    page.goto("http://localhost:8021/", wait_until="networkidle")
    page.screenshot(path=f"{OUT}/01_home.png", full_page=True)
    page.get_by_text("orchestrator", exact=True).first.click()
    box = page.locator("textarea")
    box.fill(Q)
    box.press("Enter")
    t0 = time.time()
    page.wait_for_function("document.body.innerText.includes('run_state:')", timeout=90000)
    log["answer_seconds"] = round(time.time() - t0, 2)
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{OUT}/02_chat_answer.png", full_page=True)
    body = page.inner_text("body")
    log["answer_has_values"] = {v: v in body for v in ("138", "61", "72.500.000", "64.500.000", "12,40", "B-11")}
    rp_ids = sorted(set(re.findall(r"rp_[0-9a-f]{12}", body)))
    log["rp_ids_visible_in_chat"] = rp_ids
    links = page.locator("[class*='artifact-report'], .artifact-link", has_text="rp_")
    log["rp_links"] = links.count()
    if links.count():
        links.first.click()
        page.wait_for_selector("article.report", timeout=30000)
        try:
            page.wait_for_function("document.querySelectorAll('figure.chart .chart-canvas svg').length >= 5", timeout=30000)
        except Exception as exc:
            log["chart_wait_error"] = str(exc)[:200]
        page.wait_for_timeout(1500)
        report = page.locator("article.report")
        log["report_text_has"] = {k: k in report.inner_text() for k in ("1. Bối cảnh", "2. Tóm tắt điều hành", "3. Chỉ số chính",
                                  "4. Phân tích & Insight", "5. Bằng chứng & Trực quan hóa", "6. Hạn chế & Chất lượng dữ liệu")}
        log["figures"] = page.locator("article.report figure.chart").count()
        log["rendered_svgs"] = page.locator("article.report figure.chart .chart-canvas svg").count()
        log["raw_embed_tokens_in_report"] = "{{chart_spec" in report.inner_text()
        log["chart_render_errors"] = page.locator("article.report .error-text").all_inner_texts()
        report.screenshot(path=f"{OUT}/03_report.png")
        figs = page.locator("article.report figure.chart")
        for i in range(min(figs.count(), 5)):
            figs.nth(i).screenshot(path=f"{OUT}/04_chart_{i+1}.png")
    browser.close()
json.dump(log, open(f"{OUT}/browser_log.json", "w"), ensure_ascii=False, indent=2)
print(json.dumps({k: v for k, v in log.items() if k != "console"}, ensure_ascii=False, indent=2))
print("console messages:", len(log["console"]), "errors:", [c for c in log["console"] if c["type"] == "error"][:5])
