// Optional browser check: start `uv run python -m tests.browser_server` first.
// Uses an independently installed Playwright and Chromium; no runtime JS dependency.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("http://127.0.0.1:8765");
    assert(await page.locator("#batch").isDisabled());
    assert(await page.locator("#ask").isDisabled());
    const injection = '<img src=x onerror=window.docwikiPwned=true>';
    await page.locator("#document").setInputFiles({
      name: "source.json", mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify({ cloud: "ExampleCloud", note: injection }))
    });
    const question = `<script>window.docwikiPwned=true</script> Which cloud?`;
    await page.locator("#questions").setInputFiles({
      name: "questions.json", mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify([question, question]))
    });
    await page.locator("#batch").click();
    await page.waitForFunction(() => document.querySelector("#progress").textContent.includes("Reading"));
    assert(await page.locator("#batch").isDisabled());
    await page.waitForFunction(() => document.querySelectorAll(".result").length === 2);
    assert.equal(await page.locator(".result h3").first().textContent(), question);
    await page.locator("details summary").first().click();
    assert((await page.locator("details pre").first().textContent()).includes(injection));
    assert.equal(await page.locator("#results img, #results script").count(), 0);
    assert.equal(await page.evaluate(() => window.docwikiPwned), undefined);
    const downloadPromise = page.waitForEvent("download");
    await page.locator("#export").click();
    const download = await downloadPromise;
    const exported = JSON.parse(await fs.readFile(await download.path(), "utf8"));
    assert.equal(exported.results.length, 2);
    assert.notEqual(exported.results[0].id, exported.results[1].id);
    assert.equal(exported.results[0].citations[0].locations[0].json_path, "$");
    await page.locator("#upload").click();
    await page.waitForFunction(() => document.querySelector("#document-status").textContent.includes("Reused index"));
    await page.locator("#question").fill("Hosting provider?");
    await page.locator("#ask").click();
    await page.waitForFunction(() => document.querySelectorAll(".result").length === 1);
    assert.equal(await page.locator(".result h3").textContent(), "Hosting provider?");
    await page.locator("#questions").setInputFiles({
      name: "bad.json", mimeType: "application/json", buffer: Buffer.from('[""]')
    });
    await page.locator("#batch").click();
    await page.locator("#error").waitFor({ state: "visible" });
    assert((await page.locator("#error").textContent()).includes("Questions must contain"));
    assert(await page.locator("#batch").isEnabled());
    await page.locator("#document").setInputFiles(path.resolve("evaluation/sources/policy.pdf"));
    assert(await page.locator("#ask").isDisabled());
    await page.locator("#questions").setInputFiles({
      name: "questions.json", mimeType: "application/json", buffer: Buffer.from('["Hosting provider?"]')
    });
    await page.locator("#batch").click();
    await page.waitForFunction(() => document.querySelector("details summary")?.textContent.includes("PDF page 2"));
    await page.locator("details summary").first().click();
    await fs.mkdir("artifacts", { recursive: true });
    await page.screenshot({ path: "artifacts/browser-desktop.png", fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({ path: "artifacts/browser-mobile.png", fullPage: true });
    assert.deepEqual(errors, []);
    console.log("Browser smoke passed: uploads, loading, duplicates, citations, reuse, single questions, errors, safe text, JSON export, responsive layout.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
