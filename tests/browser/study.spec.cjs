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
