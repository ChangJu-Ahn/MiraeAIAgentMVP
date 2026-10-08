const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

(async () => {
  const base = process.env.CHAT_URL || "http://127.0.0.1:8765";
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    const messages = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("websocket", socket => socket.on("framesent", frame => {
      if (String(frame.payload).includes('"client_message"')) messages.push(frame.payload);
    }));
    await page.goto(base, { waitUntil: "networkidle" });
    const picker = page.locator('a[href="#question-examples"]');
    await picker.waitFor({ timeout: 10000 });
    const composer = page.locator("#chat-input");
    const evaluation = await (await page.request.get(base + "/public/evaluation-data.json")).json();
    const question = evaluation.rows[0].question;
    const beforeMessages = messages.length;
    await picker.click();
    const dialog = page.locator("#question-examples-dialog");
    await page.locator(".question-example").first().waitFor();
    assert.equal(await page.locator(".question-example").count(), evaluation.rows.length);
    await page.locator(".question-example").first().click();
    assert.equal(await composer.inputValue(), question);
    assert.equal(await dialog.evaluate(node => node.open), false);
    assert.equal(await composer.evaluate(node => node === document.activeElement), true);
    await page.waitForTimeout(300);
    assert.equal(messages.length, beforeMessages, "selection must not send a message");
    await composer.fill("사용자가 작성 중인 질문");
    await picker.click();
    page.once("dialog", prompt => prompt.dismiss());
    await page.locator(".question-example").nth(1).click();
    assert.equal(await composer.inputValue(), "사용자가 작성 중인 질문");
    assert.equal(await dialog.evaluate(node => node.open), true);
    page.once("dialog", prompt => prompt.accept());
    await page.locator(".question-example").nth(1).click();
    assert.equal(await composer.inputValue(), evaluation.rows[1].question);
    await composer.press("End");
    await composer.pressSequentially(" 수정");
    assert.ok((await composer.inputValue()).endsWith(" 수정"));
    await picker.click();
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden", timeout: 3000 });
    assert.equal(await dialog.evaluate(node => node.open), false);
    assert.equal(await page.locator("#question-examples-dialog").count(), 1);
    await page.setViewportSize({ width: 390, height: 844 });
    const settingsSheet = page.locator('[role="dialog"][data-state="open"]').filter({ hasText: "설정 패널" });
    if (await settingsSheet.isVisible()) {
      await settingsSheet.getByRole("button", { name: "취소", exact: true }).click();
      await settingsSheet.waitFor({ state: "hidden" });
    }
    await picker.click();
    const metrics = await dialog.evaluate(node => ({
      width: node.getBoundingClientRect().width,
      right: node.getBoundingClientRect().right,
      viewport: innerWidth,
    }));
    assert.ok(metrics.right <= metrics.viewport && metrics.width <= metrics.viewport);
    if (process.env.BROWSER_ARTIFACTS_DIR) {
      await page.screenshot({
        path: path.join(process.env.BROWSER_ARTIFACTS_DIR, "question-picker-mobile.png"),
        fullPage: true,
      });
    }
    await page.keyboard.press("Escape");
    assert.deepEqual(errors, []);
    const retryPage = await browser.newPage();
    await retryPage.route("**/public/evaluation-data.json", route =>
      route.fulfill({ status: 503, body: "Unavailable" }));
    await retryPage.goto(base, { waitUntil: "networkidle" });
    await retryPage.locator('a[href="#question-examples"]').click();
    await retryPage.locator('#question-examples-status[role="alert"]').waitFor();
    assert.match(await retryPage.locator("#question-examples-status").innerText(), /불러오지 못했습니다/);
    await retryPage.getByRole("button", { name: "질문 예시 닫기" }).click();
    await retryPage.unroute("**/public/evaluation-data.json");
    await retryPage.locator('a[href="#question-examples"]').click();
    await retryPage.locator(".question-example").first().waitFor();
    assert.equal(await retryPage.locator(".question-example").count(), evaluation.rows.length);
    console.log("Question picker: 16 questions, editable prefill, no send, draft protection, keyboard and mobile checks passed.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
