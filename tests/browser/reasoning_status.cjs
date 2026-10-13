const assert = require("node:assert/strict");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage();
    await page.goto(process.env.CHAT_URL || "http://127.0.0.1:8766", {
      waitUntil: "networkidle",
    });
    await page.locator("#chat-input").fill("상태 표시 확인");
    await page.locator("#chat-submit").click();
    const reasoning = page.locator('[id="step-생각 중"]');
    await reasoning.waitFor();
    assert.equal((await reasoning.innerText()).trim(), "생각 중");
    assert.equal(await reasoning.locator(":scope > span").first().isVisible(), false);
    const reasoningAccordion = page.locator('button[id="step-생각 중"]');
    await reasoningAccordion.waitFor();
    await reasoningAccordion.click();
    const tool = page.locator('[id="step-🔧 search_tables"]');
    await tool.waitFor();
    assert.match(await tool.innerText(), /사용 중/);
    await page.getByText("상태 표시 확인 완료", { exact: true }).waitFor();
    const completed = page.locator('[id="step-생각 중 (총 2.0s)"]');
    assert.equal((await completed.innerText()).trim(), "생각 중 (총 2.0s)");
    assert.match(await tool.innerText(), /사용됨/);
    if ((await completed.getAttribute("aria-expanded")) !== "true") await completed.click();
    await page.getByText("검색 근거를 확인합니다.", { exact: true }).waitFor();
    console.log("Reasoning label: no active/completed prefix; tool status and reasoning detail preserved.");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
