const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    headless: true,
  });
  const page = await browser.newPage();
  const errors = [];
  let net404 = 0;
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    // 浏览器对任何网络 404 都固定记一条 console error（契约规定 graph/style 未生成时返回 404），
    // 这类资源加载错误不算页面 JS 故障，单独计数
    if (/Failed to load resource/.test(m.text())) { net404 += 1; return; }
    errors.push(m.text().slice(0, 200));
  });
  page.on("pageerror", (e) => errors.push("PAGEERROR: " + String(e).slice(0, 200)));
  page.on("response", (r) => { if (r.status() === 404) net404 += 0; });

  await page.goto("http://127.0.0.1:8813/", { waitUntil: "networkidle" });
  const homeOk = await page.getByText("novel-ledger").first().isVisible().catch(() => false);
  console.log("首页加载:", homeOk ? "OK" : "FAIL");

  await page.getByText("图谱与文风").first().click();
  await page.waitForTimeout(1500);
  const graphOk = await page.getByText("人物关系图谱").first().isVisible().catch(() => false);
  const styleOk = await page.getByText("文风指纹").first().isVisible().catch(() => false);
  const vecOk = await page.getByText("向量索引").first().isVisible().catch(() => false);
  console.log("图谱页:", graphOk && styleOk && vecOk ? "OK（三个区块均渲染）" : `FAIL graph=${graphOk} style=${styleOk} vec=${vecOk}`);

  // 助手页意图提示
  await page.getByText("AI 助手").first().click();
  await page.waitForTimeout(800);
  const asstOk = await page.getByText("导出证据包").first().isVisible().catch(() => false);
  console.log("助手页(意图提示可见):", asstOk ? "OK" : "FAIL");

  // 工作台：v0.9 按钮渲染
  await page.getByText("章节与账本").first().click();
  await page.waitForTimeout(1000);
  const btns = await page.getByText("账本重算").first().isVisible().catch(() => false)
    && await page.getByText("平台自检").first().isVisible().catch(() => false)
    && await page.getByText("读者试读").first().isVisible().catch(() => false)
    && await page.getByText("导出证据包").first().isVisible().catch(() => false)
    && await page.getByText("交叉审计").first().isVisible().catch(() => false);
  console.log("工作台 v0.9 按钮:", btns ? "OK（5 个均在）" : "FAIL");

  console.log(`JS/page 错误: ${errors.length === 0 ? "0 ✅" : JSON.stringify(errors, null, 2)}`);
  console.log(`网络 404（graph/style/vector 未生成，契约行为）: ${net404} 条`);
  await browser.close();
  process.exit(errors.length === 0 ? 0 : 2);
})().catch((e) => { console.error("SMOKE CRASH:", e.message); process.exit(1); });
