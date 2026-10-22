const {test: base, expect} = require("@playwright/test");
const {spawn} = require("node:child_process");
const test = base.extend({baseURL: async ({}, use) => {
  const child = spawn("python", ["tests/browser_server.py"], {env:{...process.env, MST_TEST_PORT:"0"}});
  const url = await new Promise((resolve,reject) => {
    child.stdout.once("data", (data) => resolve(String(data).trim()));
    child.stderr.on("data", (data) => reject(new Error(String(data))));
    child.once("exit", (code) => reject(new Error(`Fixture server exited: ${code}`)));
  });
  try { await use(url); } finally { child.kill("SIGTERM"); }
}});

test("refresh resumes reading, preserves draft and keeps answers folded", async ({page}, testInfo) => {
  const errors = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await expect(page.locator("#learningSpine li")).toHaveCount(1);
  await expect(page.locator("#learningSpineNotice")).toBeHidden();
  await page.screenshot({path:testInfo.outputPath("route.png")});
  await page.locator("#startLearning").click();
  const answer = page.locator("#lessonContent textarea").first();
  await answer.fill("中文公式 x²\naddi x5, x0, 10");
  await page.locator("#lessonContent .practice").first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
  const before = await page.evaluate(() => scrollY);
  await expect(page.locator("#saveStatus")).toContainText("已保存在本机");
  await page.evaluate(() => localStorage.clear()); // Restore from local service, not the browser cache.
  await page.reload();
  await expect(page.locator("#learnView")).toBeVisible();
  await expect(page.locator("#lessonContent textarea").first()).toHaveValue("中文公式 x²\naddi x5, x0, 10");
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(Math.max(0,before - 120));
  await expect(page.locator("#lessonContent .practice details[open]")).toHaveCount(0);
  await page.locator("#nextUnit").click();
  await expect(page.locator("#lessonContent h2")).toHaveText("第二个知识点");
  await expect(page.locator(".prerequisite-links")).toContainText("从证据到机制");
  await expect(page.locator("#lessonContent h2")).toBeInViewport();
  await page.screenshot({path:testInfo.outputPath("lesson.png")});
  await expect(page.locator("#progressText")).toContainText("0/2");
  await page.locator('#lessonContent [data-view="route"]').click();
  await expect(page.locator("#resumeLearning")).toBeVisible();
  await page.locator("#resumeLearning").click();
  await expect(page.locator("#lessonContent h2")).toHaveText("第二个知识点");
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.evaluate(() => document.documentElement.clientWidth));
  expect(errors).toEqual([]);
});

test("student can compare the actual source page beside its explanation", async ({page}, testInfo) => {
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#startLearning").click();
  const viewer = page.locator("#lessonContent .material-pages");
  await expect(viewer).toBeVisible();
  await expect(viewer.locator("summary")).toContainText("3 页");
  const image = () => viewer.locator("figure:not([hidden]) img");
  await image().scrollIntoViewIfNeeded();
  await expect.poll(() => image().evaluate((node) => node.naturalWidth)).toBeGreaterThan(0);
  await expect(viewer.locator("figure:not([hidden]) figcaption")).toContainText("第 1 页");
  await expect(viewer.locator('[data-page-step="-1"]')).toBeDisabled();
  await viewer.locator('[data-page-step="1"]').click();
  await expect(viewer.locator("figure:not([hidden]) figcaption")).toContainText("第 2 页");
  await viewer.locator('[data-page-step="1"]').click();
  await expect(viewer.locator("figure:not([hidden]) figcaption")).toContainText("第 10 页");
  await expect(viewer.locator('[data-page-step="1"]')).toBeDisabled();
  await expect(viewer.locator("figure:not([hidden]) a")).toHaveAttribute("href", /page-0010\.png$/);
  await expect(page.locator("#progressText")).toContainText("0/2");
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.evaluate(() => document.documentElement.clientWidth));
  await page.screenshot({path:testInfo.outputPath("material-page.png")});
  await page.locator("#nextUnit").click();
  await expect(page.locator("#lessonContent .material-pages")).toHaveCount(0);
});

test("a missing source image gives an honest readable fallback", async ({page}) => {
  await page.route("**/assets/derived/rendered/**", (route) => route.fulfill({status:404,contentType:"application/json",body:'{"error":"missing"}'}));
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#startLearning").click();
  const viewer = page.locator("#lessonContent .material-pages");
  await viewer.scrollIntoViewIfNeeded();
  await expect(viewer.locator("figure:not([hidden]) .page-image-error")).toBeVisible();
  await expect(viewer.locator("figure:not([hidden]) img")).toBeHidden();
  await expect(page.locator("#lessonContent h2")).toHaveText("从证据到机制");
});

test("a slowly loaded original page cannot move the student's reading position", async ({page}) => {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  await page.route("**/assets/derived/rendered/**", async (route) => { await held; await route.continue(); });
  try {
    await page.goto("/");
    await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
    await page.locator("#startLearning").click();
    const image = page.locator("#lessonContent figure:not([hidden]) img");
    await image.scrollIntoViewIfNeeded();
    expect(await image.evaluate((node) => node.naturalWidth)).toBe(0);
    const heightBefore = await image.evaluate((node) => node.getBoundingClientRect().height);
    const practice = page.locator("#lessonContent .practice").first();
    await practice.scrollIntoViewIfNeeded();
    const before = await practice.evaluate((node) => node.getBoundingClientRect().top);
    release();
    await expect.poll(() => image.evaluate((node) => node.naturalWidth)).toBeGreaterThan(0);
    expect(await image.evaluate((node) => node.getBoundingClientRect().height)).toBe(heightBefore);
    expect(Math.abs(await practice.evaluate((node) => node.getBoundingClientRect().top) - before)).toBeLessThan(2);
  } finally { release(); }
});

test("exported HTML keeps real page images and folded answers without its app", async ({page, request}) => {
  const response = await request.get("/api/exports/html");
  expect(response.ok()).toBeTruthy();
  const document = await response.text();
  const requests = [];
  page.on("request", (item) => requests.push(item.url()));
  // No source asset, app script or local server is available to this document.
  await page.route("**/*", (route) => route.abort());
  await page.setContent(document);
  const image = page.locator(".material-page img").first();
  await image.scrollIntoViewIfNeeded();
  await expect.poll(() => image.evaluate((node) => node.naturalWidth)).toBe(1);
  await expect(image).toHaveAttribute("src", /^data:image\/png;base64,/);
  await expect(page.locator(".material-page")).toHaveCount(3);
  await expect(page.locator(".material-page figcaption").last()).toContainText("第 10 页");
  await expect(page.locator(".practice details[open], .review details[open]")).toHaveCount(0);
  await page.locator(".review summary").first().click();
  const back = page.locator(".review details[open] a").first();
  await back.click();
  expect(await page.evaluate(() => location.hash)).not.toBe("");
  expect(requests.filter((url) => !url.startsWith("data:") && !url.startsWith("about:"))).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy();
});

test("closing waits for a slow write and the newer answer before reporting saved", async ({page, request}) => {
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#startLearning").click();
  const answer = page.locator("#lessonContent textarea").first();
  let release, started;
  const held = new Promise((resolve) => { release = resolve; });
  const reached = new Promise((resolve) => { started = resolve; });
  let delayed = false;
  await page.route("**/api/progress/*", async (route) => {
    if (route.request().method() === "POST" && !delayed) {
      delayed = true; started(); await held;
    }
    await route.continue();
  });
  await answer.fill("先写的答案");
  await reached;
  await answer.fill("关窗前刚写的答案 x²\naddi x5, x0, 10");
  const closing = page.evaluate(() => window.StudyDesktop.prepareToClose());
  release();
  expect(await closing).toEqual({saved:true,busy:false});
  const saved = await (await request.get("/api/jobs/latest")).json();
  expect(saved.job).toBeNull();
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await expect(page.locator("#lessonContent textarea").first()).toHaveValue("关窗前刚写的答案 x²\naddi x5, x0, 10");
});

test("closing immediately after entering a lesson records the new reading view", async ({page}) => {
  await page.goto("/");
  await expect.poll(() => page.evaluate(() => window.StudyDesktop?.ready)).toBe(true);
  expect(await page.evaluate(async () => {
    document.getElementById("startLearning").click();
    return window.StudyDesktop.prepareToClose();
  })).toEqual({saved:true,busy:false});
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await expect(page.locator("#learnView")).toBeVisible();
});

test("close does not claim an answer conflict was saved", async ({page}) => {
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#startLearning").click();
  await page.evaluate(() => window.StudyDesktop.prepareToClose());
  await page.route("**/api/progress/*", async (route) => {
    if (route.request().method() === "POST") return route.fulfill({status:409,contentType:"application/json",body:JSON.stringify({error:"另一个页面已更新进度"})});
    return route.continue();
  });
  await page.locator("#lessonContent textarea").first().fill("冲突中的草稿");
  expect(await page.evaluate(() => window.StudyDesktop.prepareToClose())).toEqual({saved:false,busy:false});
  await expect(page.locator("#saveStatus")).toContainText("另一个页面");
});

test("unit completion is reversible and review returns to the lesson", async ({page}) => {
  await page.goto("/");
  await expect(page.locator("#startLearning")).toBeEnabled();
  await page.locator("#startLearning").click();
  await page.locator("#markUnit").click();
  await expect(page.locator("#progressText")).toContainText("1/2");
  await page.locator("#markUnit").click();
  await expect(page.locator("#progressText")).toContainText("0/2");
  await page.locator('[data-view="review"]').click();
  const card = page.locator(".review-card").first();
  await card.locator("textarea").fill("独立回答");
  await card.locator("summary").click();
  await card.locator("[data-return-unit]").click();
  await expect(page.locator("#learnView")).toBeVisible();
  await page.locator("#nextUnit").click();
  await page.locator(".prerequisite-links button").click();
  await expect(page.locator("#lessonContent h2")).toHaveText("从证据到机制");
});

test("revised content invalidates only its own progress and different courses stay separate", async ({page, request}) => {
  const response = await request.get("/study-guide.json");
  const guide = await response.json();
  await page.goto("/");
  await expect(page.locator("#startLearning")).toBeEnabled();
  await page.locator("#startLearning").click();
  await page.locator("#lessonContent textarea").first().fill("旧版作答");
  await page.locator("#markUnit").click();
  await page.locator("#nextUnit").click();
  await page.locator("#markUnit").click();
  await expect(page.locator("#progressText")).toContainText("2/2");
  guide.units[0].why = "修订后的逻辑说明";
  const openGuide = async () => {
    await page.locator("#guideFile").setInputFiles({name:"讲义.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify(guide))});
  };
  await openGuide();
  await expect(page.locator("#progressText")).toContainText("1/2");
  await page.locator('#lessonContent [data-view="route"]').click();
  await page.locator("#startLearning").click();
  await expect(page.locator("#lessonContent textarea").first()).toHaveValue("");
  await expect(page.locator("#lessonContent")).toContainText("修订后的逻辑说明");
  guide.lesson_id = `course::${"b".repeat(64)}`;
  await openGuide();
  await expect(page.locator("#progressText")).toContainText("0/2");
  await expect(page.locator("#downloads")).toBeHidden();
});

test("upload completes through real job stages and a bad upload preserves it", async ({page}) => {
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  await page.locator("#subject").selectOption("mathematics");
  await page.locator("#sourceFiles").setInputFiles({name:"课堂.md",mimeType:"text/markdown",buffer:Buffer.from("# 函数\n输入经过运算得到输出。")});
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("草稿已生成", {timeout:15000});
  await expect(page.locator("#draftNotice")).toBeVisible();
  const title = await page.locator("#guideTitle").textContent();
  await page.locator("#inputMode").selectOption("new");
  await page.locator("#sourceFiles").setInputFiles({name:"broken.pptx",mimeType:"application/octet-stream",buffer:Buffer.from("broken-zip")});
  await page.locator("#generateButton").click();
  await expect(page.locator("#retryJob")).toBeVisible();
  await expect(page.locator("#guideTitle")).toHaveText(title);
  await page.reload();
  await expect(page.locator("#retryJob")).toBeVisible();
  await expect(page.locator("#guideTitle")).toHaveText(title);
  await page.locator("#retryJob").click();
  await expect(page.locator("#uploadMessage")).toContainText("无法打开");
});

test("a mathematics student gets the original negative-number explanation and can try its variant", async ({page}, testInfo) => {
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  await page.locator("#subject").selectOption("mathematics");
  const source = "# 负数与进制转换\nBinary to decimal: -0b101.1";
  await page.locator("#sourceFiles").setInputFiles({name:"数的表示.md", mimeType:"text/markdown", buffer:Buffer.from(source)});
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("草稿已生成", {timeout:15000});
  await page.locator("#startLearning").click();
  await expect(page.locator("#lessonContent .grip")).toContainText("(-101.1)₂");
  const example = page.locator("#lessonContent .example");
  expect(await example.locator("ol li").count()).toBeGreaterThanOrEqual(3);
  await expect(example).toContainText("(-5.5)₁₀");
  await expect(example).toContainText("最前面的负号作用于整个数值");
  await example.screenshot({path:testInfo.outputPath("numerical-example.png")});
  await expect(page.locator("#lessonContent .practice details[open]")).toHaveCount(0);
  const variant = page.locator("#lessonContent .practice").last();
  await variant.locator("textarea").fill("原数增加 0.5 后为 -5，负号仍保留。");
  await variant.locator("summary").click();
  await expect(variant).toContainText("(-5)₁₀");
  await expect(page.locator("#progressText")).toContainText("0/1");
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.evaluate(() => document.documentElement.clientWidth));
});

test("a student can follow borrowing, solve a concrete variant and resume with answers folded", async ({page}, testInfo) => {
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  await page.locator("#subject").selectOption("computer-systems");
  await page.locator("#sourceFiles").setInputFiles({name:"借位.md", mimeType:"text/markdown", buffer:Buffer.from("# 二进制减法\nBinary subtraction: 10000-00001")});
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("草稿已生成", {timeout:15000});
  await page.locator("#startLearning").click();
  const example = page.locator("#lessonContent .example");
  await expect(example).toContainText("(01111)₂");
  await expect(example).toContainText("0 - 1 - 借位 0 = -1");
  await expect(example).toContainText("借来的 1 相当于本列的 2");
  expect(await example.locator("ol li").count()).toBeGreaterThanOrEqual(7);
  await example.screenshot({path:testInfo.outputPath("binary-borrow-example.png")});
  await expect(page.locator("#lessonContent .practice")).toHaveCount(3);
  await expect(page.locator("#lessonContent .practice details[open]")).toHaveCount(0);
  const process = page.locator("#lessonContent .practice").nth(1);
  await process.locator("textarea").fill("本位=1；借位=1。");
  await process.locator("summary").click();
  await expect(process).toContainText("本位=1；借位=1");
  const variant = page.locator("#lessonContent .practice").last();
  await expect(variant).toContainText("(10001)₂ - (00001)₂");
  await variant.locator("textarea").fill("10000，重新计算后借位链消失。");
  await variant.locator("summary").click();
  await expect(variant).toContainText("(10000)₂");
  await expect(page.locator("#saveStatus")).toContainText("已保存在本机");
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.evaluate(() => document.documentElement.clientWidth));
  await page.reload();
  await expect(page.locator("#lessonContent .practice").last().locator("textarea")).toHaveValue("10000，重新计算后借位链消失。");
  await expect(page.locator("#lessonContent .practice details[open]")).toHaveCount(0);
  await expect(page.locator("#progressText")).toContainText("0/1");
});

test("unexplained materials stay readable without mock exercises or completion", async ({page, request}, testInfo) => {
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  await page.locator("#subject").selectOption("mathematics");
  const text = "# 有界单调数列\n单调递增数列的极限与上确界。\n" + "尚待补充证明细节。".repeat(40) + "最后的限制条件不能漏掉。";
  await page.locator("#sourceFiles").setInputFiles({name:"合成证明材料.md",mimeType:"text/markdown",buffer:Buffer.from(text)});
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("草稿已生成", {timeout:15000});
  await expect(page.locator("#routeCards")).toContainText("精讲待补充");
  await expect(page.locator("#startLearning")).toHaveText("查看已整理的材料");
  await page.locator("#startLearning").click();
  await expect(page.locator("#lessonContent .content-gap")).toBeVisible();
  await expect(page.locator("#lessonContent")).toContainText("最后的限制条件不能漏掉");
  await expect(page.locator("#lessonContent .practice, #lessonContent .example, #markUnit")).toHaveCount(0);
  await expect(page.locator("#lessonContent .bridge, #lessonContent .predict-box")).toHaveCount(0);
  await expect(page.locator("#progressText")).toContainText("0/1");
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.evaluate(() => document.documentElement.clientWidth));
  await page.locator("#lessonContent").screenshot({path:testInfo.outputPath("material-only.png")});
  for (const format of ["md","html"]) {
    const document = await (await request.get(`/api/exports/${format}`)).text();
    expect(document).toContain("精讲待补充");
    expect(document).toContain("最后的限制条件不能漏掉");
    expect(document).not.toContain("展开答案与解析");
  }
  await page.locator("[data-add-explanation]").click();
  await expect(page.locator("#materialPanel")).toHaveAttribute("open", "");
  await expect(page.locator("#generationMode")).toHaveValue("none");
  await page.locator("#nextUnit").click();
  await expect(page.locator("#reviewItems")).toContainText("暂不提供闭卷题");
});

test("student can add a transcript, replace one file and reopen saved material receipts", async ({page}, testInfo) => {
  const errors = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  const put = async (name, content) => page.locator("#sourceFiles").setInputFiles({name, mimeType:"application/octet-stream", buffer:Buffer.from(content)});
  await put("进制.md", "# 数的表示\n把二进制 101 转换为十进制。");
  await put("课堂录音.mp3", "synthetic-audio");
  await put("多余.txt", "temporary");
  await expect(page.locator(".pending-files li")).toHaveCount(3);
  await page.getByRole("button", {name:"移除 多余.txt", exact:true}).click();
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("草稿已生成", {timeout:15000});
  await expect(page.locator("#materialResults li")).toHaveCount(2);
  await expect(page.locator("#materialResults")).toContainText("录音尚未转写");
  await expect(page.locator("#inputMode")).toHaveValue("revise");
  await expect(page.locator("#subject")).toBeDisabled();
  const original = await (await page.request.get("/study-guide.json")).json();
  await page.reload();
  await page.locator("#showMaterials").click();
  await expect(page.locator("#materialResults li")).toHaveCount(2);
  await expect(page.locator("#materialResults input:checked")).toHaveCount(2);
  await page.locator("#materialResults li").filter({hasText:"课堂录音.mp3"}).locator('input[type="checkbox"]').uncheck();
  const name = "教师转写与课堂补充".repeat(4) + ".vtt";
  await put(name, "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n把二进制 101 转换为十进制，按位权相加。\n");
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("草稿已生成", {timeout:15000});
  await expect(page.locator("#materialResults li")).toHaveCount(2);
  await expect(page.locator("#materialResults")).not.toContainText("课堂录音.mp3");
  await expect(page.locator("#materialResults")).toContainText("转写已读取");
  const revised = await (await page.request.get("/study-guide.json")).json();
  expect(revised.lesson_id).toEqual(original.lesson_id);
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.evaluate(() => document.documentElement.clientWidth));
  await page.screenshot({path:testInfo.outputPath("material-repair.png")});
  expect(errors).toEqual([]);
});

test("unfinished mainline and source limitations are readable without executing source text", async ({page, request}) => {
  const guide = await (await request.get("/study-guide.json")).json();
  guide.route.chain = [];
  guide.source_index[0].note = '缺少图中坐标，待复核。<script>window.sourceNoteExecuted = true</script>';
  await page.goto("/");
  await expect(page.locator("#startLearning")).toBeEnabled();
  await page.locator("#guideFile").setInputFiles({name:"教学草稿.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify(guide))});
  await expect(page.locator("#learningSpineNotice")).toBeVisible();
  await expect(page.locator("#learningSpineNotice")).toContainText("主线待梳理");
  await page.locator("#sourcesSection > details > summary").click();
  await expect(page.locator("#sourceList")).toContainText(guide.source_index[0].note);
  await expect(page.locator("#sourceList script")).toHaveCount(0);
  expect(await page.evaluate(() => window.sourceNoteExecuted)).toBeUndefined();
});

test("model teaching needs fresh scope consent and never restores credentials", async ({page, request}, testInfo) => {
  const initial = await (await request.get("/study-guide.json")).json();
  const posts = [];
  page.on("request", (req) => { if (req.method() === "POST" && /\/api\/jobs(?:\/|$)/.test(req.url())) posts.push(req); });
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  await expect(page.locator("#generationMode")).toHaveValue("none");
  await page.locator("#sourceFiles").setInputFiles({name:"因果解释.md",mimeType:"text/markdown",buffer:Buffer.from("# 因果解释\n解释变化需要检查条件、机制和对照证据。")});
  await page.locator("#generationMode").selectOption("model");
  await page.locator("#modelProvider").selectOption("compatible");
  await page.locator("#modelBaseUrl").fill(initial._test_model_url);
  await page.locator("#modelName").fill("synthetic-model");
  await page.locator("#modelApiKey").fill("synthetic-browser-secret");
  await expect(page.locator("#sendDestination")).toContainText(initial._test_model_url);
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("确认本次材料发送范围");
  expect(posts).toHaveLength(0);
  await expect(page.locator("#modelApiKey")).toHaveValue("synthetic-browser-secret");
  await page.locator("#modelConsent").check();
  await page.locator("#modelName").fill("changed-model");
  await expect(page.locator("#modelConsent")).not.toBeChecked();
  await expect(page.locator("#uploadMessage")).toContainText("重新确认");
  await page.locator("#modelConsent").check();
  await expect(page.locator("#uploadMessage")).toContainText("已确认本次发送范围");
  await page.screenshot({path:testInfo.outputPath("model-consent.png"),fullPage:true});
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("模型讲解已保存", {timeout:15000});
  await expect(page.locator("#guideTitle")).toHaveText("如何检查一个因果解释");
  await expect(page.locator("#modelApiKey")).toHaveValue("");
  await expect(page.locator("#modelConsent")).not.toBeChecked();
  const job = (await (await request.get("/api/jobs/latest")).json()).job;
  expect(job.generation.stats.checked_units).toBe(1);
  expect(JSON.stringify(job)).not.toContain("synthetic-browser-secret");
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("synthetic-browser-secret");
  await page.locator("#startLearning").click();
  await expect(page.locator("#lessonContent")).toContainText("不能认定 A 是唯一原因");
  await page.reload();
  await expect(page.locator("#generationMode")).toHaveValue("none");
  await expect(page.locator("#modelApiKey")).toHaveValue("");
  expect(posts).toHaveLength(1);
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.evaluate(() => document.documentElement.clientWidth));
});

test("failed model connection leaves the prior lesson readable and needs new settings", async ({page, request}) => {
  const initial = await (await request.get("/study-guide.json")).json();
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  await page.locator("#sourceFiles").setInputFiles({name:"课程.md",mimeType:"text/markdown",buffer:Buffer.from("# 因果解释\n解释变化需要检查条件、机制和对照证据。")});
  await page.locator("#generationMode").selectOption("model");
  await page.locator("#modelProvider").selectOption("compatible");
  await page.locator("#modelBaseUrl").fill(initial._test_model_url.replace("/v1", "/reject"));
  await page.locator("#modelApiKey").fill("synthetic-rejected-secret");
  await page.locator("#modelConsent").check();
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("密钥无效", {timeout:15000});
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await expect(page.locator("#modelApiKey")).toHaveValue("");
  await expect(page.locator("#retryJob")).toBeHidden();
  await page.reload();
  await expect(page.locator("#uploadMessage")).toContainText("密钥无效");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await expect(page.locator("#generationMode")).toHaveValue("none");
});

test("student transcribes selected audio with separate consent and reuses it locally after reload", async ({page, request}, testInfo) => {
  const initial = await (await request.get("/study-guide.json")).json();
  const posts = [];
  page.on("request", (req) => { if (req.method() === "POST" && /\/api\/jobs(?:\/|$)/.test(req.url())) posts.push(req); });
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  await expect(page.locator("#speechBox")).toBeHidden();
  await page.locator("#sourceFiles").setInputFiles([
    {name:"课件.md", mimeType:"text/markdown", buffer:Buffer.from("# 二进制加法\n二进制 00111 + 00001")},
    {name:"课堂录音.mp3", mimeType:"audio/mpeg", buffer:Buffer.from("synthetic-browser-audio")}
  ]);
  await expect(page.locator("#speechMode")).toHaveValue("none");
  await expect(page.locator("#generationMode")).toHaveValue("none");
  await page.locator("#speechMode").selectOption("transcribe");
  await page.locator("#speechAdvanced > summary").click();
  await page.locator("#speechProvider").selectOption("compatible");
  await page.locator("#speechBaseUrl").fill(initial._test_speech_url);
  await page.locator("#speechApiKey").fill("synthetic-browser-speech-key");
  await expect(page.locator("#speechFiles")).toHaveText("课堂录音.mp3");
  await expect(page.locator("#speechDestination")).toContainText(initial._test_speech_url);
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("确认本次录音发送范围");
  expect(posts).toHaveLength(0);
  await page.locator("#speechConsent").check();
  await page.locator("#sourceFiles").setInputFiles({name:"多余录音.mp3", mimeType:"audio/mpeg", buffer:Buffer.from("unselected-audio")});
  await expect(page.locator("#speechConsent")).not.toBeChecked();
  await page.getByRole("button", {name:"移除 多余录音.mp3",exact:true}).click();
  await expect(page.locator("#speechFiles")).not.toContainText("多余录音");
  await page.locator("#speechConsent").check();
  await page.screenshot({path:testInfo.outputPath("speech-consent.png"),fullPage:true});
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("草稿已生成",{timeout:15000});
  await expect(page.locator("#materialResults")).toContainText("转写已读取");
  await expect(page.locator("#jobStages")).toContainText("录音转写");
  const first = (await (await request.get("/api/jobs/latest")).json()).job;
  expect(first.speech.stats.requests).toBe(1);
  expect(first.materials[1].timed_segment_count).toBe(1);
  expect(JSON.stringify(first)).not.toContain("synthetic-browser-speech-key");
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("synthetic-browser-speech-key");
  await expect(page.locator("#speechApiKey")).toHaveValue("");
  await expect(page.locator("#speechConsent")).not.toBeChecked();
  await page.reload();
  await page.locator("#showMaterials").click();
  await expect(page.locator("#speechMode")).toHaveValue("none");
  await expect(page.locator("#speechApiKey")).toHaveValue("");
  await page.locator("#generateButton").click();
  await expect.poll(async () => (await (await request.get("/api/jobs/latest")).json()).job.job_id).not.toBe(first.job_id);
  await expect(page.locator("#uploadMessage")).toContainText("草稿已生成",{timeout:15000});
  await expect(page.locator("#materialResults")).toContainText("转写已读取");
  const second = (await (await request.get("/api/jobs/latest")).json()).job;
  expect(second.speech.provider).toBe("none");
  expect(second.materials[1].timed_segment_count).toBe(1);
  expect(posts).toHaveLength(2);
  expect(posts[1].postDataJSON().speech).toEqual({provider:"none"});
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", await page.evaluate(() => document.documentElement.clientWidth));
});

test("failed audio service preserves the lesson and needs fresh audio settings", async ({page, request}) => {
  const initial = await (await request.get("/study-guide.json")).json();
  await page.goto("/");
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await page.locator("#materialPanel > summary").click();
  await page.locator("#sourceFiles").setInputFiles({name:"课堂录音.mp3",mimeType:"audio/mpeg",buffer:Buffer.from("synthetic-audio")});
  await page.locator("#speechMode").selectOption("transcribe");
  await page.locator("#speechAdvanced > summary").click();
  await page.locator("#speechProvider").selectOption("compatible");
  await page.locator("#speechBaseUrl").fill(initial._test_speech_url.replace("/v1","/reject"));
  await page.locator("#speechApiKey").fill("synthetic-rejected-speech-key");
  await page.locator("#speechConsent").check();
  await page.locator("#generateButton").click();
  await expect(page.locator("#uploadMessage")).toContainText("密钥无效",{timeout:15000});
  await expect(page.locator("#guideTitle")).toHaveText("合成测试课程");
  await expect(page.locator("#speechApiKey")).toHaveValue("");
  await expect(page.locator("#speechConsent")).not.toBeChecked();
  await expect(page.locator("#retryJob")).toBeHidden();
  await page.reload();
  await expect(page.locator("#uploadMessage")).toContainText("密钥无效");
  await expect(page.locator("#speechMode")).toHaveValue("none");
});
