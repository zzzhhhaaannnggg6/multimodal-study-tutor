(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const list = (value) => Array.isArray(value) ? value : value ? [value] : [];
  const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const lines = (value) => esc(value).replace(/\n/g, "<br>");

  const demoGuide = {
    guide_version: "1.0", guide_kind: "student-study-guide", title: "从证据到机制：一节可独立学习的示范课", subject: "generic", profile: "generic", language: "zh-CN",
    route: { central_question: "为什么解释一个结论时，不能只说结论本身？", outcomes: ["指出材料中可以直接观察到的证据", "说明证据如何通过中间机制产生结果", "把这条链迁移到一个新案例"], prerequisites: ["能区分事实和解释"], chain: ["看见证据", "找出机制", "检查结果"], estimated_minutes: 18 },
    units: [{ unit_id: "demo::u001", title: "从证据到机制", question: "解释为什么不能跳过中间机制？", one_sentence: "完整解释必须把证据、机制和结果连起来。", why: "只有这样，换一个条件或案例时，你才知道结论是否仍然成立。", prerequisites: ["能区分事实和解释"], visual_refs: ["demo::p001", "demo::p002"], material_explanation: "课件先提出问题，再要求沿步骤追踪机制。", teacher_increment: "老师提醒：先确定材料中能直接观察到的事实，再补上中间机制。", tutor_bridge: "证据是起点，机制说明‘为什么会这样’，结果是最后要解释的现象。", step_chain: ["列出可观察证据", "说明中间机制", "检查机制是否足以推出结果"], worked_examples: [{ title: "完整例题", question: "把一个新案例拆成证据、机制和结果。", setup: "先不要急着写结论。", steps: ["圈出材料直接给出的事实。", "写出事实如何导致结果的中间过程。", "检查换一个条件后，这个过程是否还成立。"], answer: "证据不能直接等同于结论；必须说明中间机制。", variation: "如果机制改变，重新检查结论。", complete: true }], misconceptions: [{ wrong: "只要结果和材料一致，解释就完整了。", correct: "还要说明证据到结果之间的机制。", correction: "把中间过程写成一步或几步可检查的关系。" }], practice_items: [{ practice_id: "demo::p001", prompt: "为什么不能从证据直接跳到结论？", kind: "retrieval", difficulty: "基础", answer: "因为缺少机制，无法说明条件如何产生结果。", explanation: "先写证据，再写机制，最后检查结果是否由机制推出。", unit_id: "demo::u001" }], priority_label: "必须掌握：理解主干", assessment_signal: "课堂强调，但尚不足以判断考试要求", source_refs: [{ kind: "material", label: "材料依据", ref: "demo::p002", page: 2, verified: true, status: "covered" }], status: "complete", internal_understanding_level: "U3", internal_assessment_level: "E1" }],
    review_items: [{ practice_id: "demo::p001", prompt: "为什么不能从证据直接跳到结论？", answer: "因为缺少机制，无法说明条件如何产生结果。", explanation: "先写证据，再写机制，最后检查结果是否由机制推出。", unit_id: "demo::u001" }],
    source_index: [{ kind: "material", label: "材料依据", ref: "demo::p001", page: 1, status: "covered", verified: true }],
    generation_report: { status: "complete", provider: "demo", total_pages: 2, covered_pages: 2, total_segments: 2, aligned_segments: 2, unresolved_items: [], missing_fields: [], warnings: [] }, notes: []
  };

  const state = { guide: demoGuide, view: "route", unitIndex: 0, sourceKind: "demo", completed: new Set() };
  const units = () => list(state.guide.units);
  const activeUnit = () => units()[state.unitIndex] || units()[0];
  const progressKey = () => `mst-progress:${state.guide.lesson_id || state.guide.title || "study-guide"}`;

  function readProgress() {
    state.completed = new Set();
    try {
      const raw = JSON.parse(localStorage.getItem(progressKey()) || "[]");
      state.completed = new Set(list(raw).map(String));
    } catch (_) { /* private browsing or an old value: start clean */ }
  }

  function saveProgress() {
    try { localStorage.setItem(progressKey(), JSON.stringify([...state.completed])); } catch (_) { /* progress is optional */ }
  }

  function completionCount() {
    return units().filter((unit) => state.completed.has(unit.unit_id)).length;
  }

  function markUnitComplete(index = state.unitIndex) {
    const unit = units()[index];
    if (!unit) return;
    state.completed.add(unit.unit_id);
    saveProgress();
  }

  function practiceLabel(kind) {
    return ({ retrieval: "回忆", process: "过程", transfer: "迁移", comparison: "对比" }[kind] || "练习");
  }

  function setStatus(label, kind = "file") {
    $("sourceStatus").dataset.kind = kind;
    $("sourceStatusText").textContent = label;
  }

  function sourceLocation(source) {
    if (source.page !== undefined && source.page !== null) return `第 ${source.page} 页`;
    if (source.start !== undefined && source.start !== null) return `${source.start}–${source.end ?? "?"}`;
    return source.ref || "待定位";
  }

  function render() {
    const guide = state.guide;
    const route = guide.route || {};
    $("guideTitle").textContent = guide.title || "自学讲义";
    $("heroCopy").textContent = guide.report?.status === "complete" ? "按路线学习每个知识单元。先理解，再用例题和练习检查自己。" : "这份讲义包含可追溯的学习草稿；带有待确认标记的内容需要复核。";
    $("centralQuestion").textContent = route.central_question || "暂无课程问题";
    $("estimatedTime").textContent = `${route.estimated_minutes || "—"} 分钟`;
    $("outcomes").innerHTML = list(route.outcomes).map((item) => `<li>${lines(item)}</li>`).join("") || "<li>等待生成学习目标</li>";
    $("prerequisites").innerHTML = list(route.prerequisites).map((item) => `<li>${lines(item)}</li>`).join("") || "<li>暂无额外先修要求</li>";
    $("unitCount").textContent = `${units().length} 个知识单元`;
    $("draftNotice").hidden = guide.report?.status === "complete";
    const warningCount = list(guide.report?.warnings).length;
    const visualPending = Number(guide.report?.visual_review_pages || 0);
    const supplementCount = Number(guide.report?.supplement_segments || 0);
    $("draftText").textContent = warningCount || visualPending || supplementCount
      ? `页面文字已读出；${visualPending} 页需要视觉复核，${supplementCount} 段语音保留为课堂补充。`
      : "已保留可定位来源；当前没有待确认的视觉或语音结构。";
    const done = completionCount();
    const total = units().length;
    $("progressBar").style.width = total ? `${Math.round(done / total * 100)}%` : "0%";
    $("progressText").textContent = total ? `${done}/${total} 个知识点已完成` : "还没有知识单元";
    $("resumeLearning").hidden = done === 0 || done >= total;
    renderRoute(); renderLearn(); renderReview(); renderSources(); switchView(state.view);
  }

  function renderRoute() {
    $("routeCards").innerHTML = units().map((unit, index) => {
      const done = state.completed.has(unit.unit_id);
      return `<button class="unit-card ${done ? "is-done" : ""}" data-unit-index="${index}" type="button"><span class="unit-number">${done ? "✓" : String(index + 1).padStart(2, "0")}</span><span><strong>${esc(unit.title)}</strong><small>${esc(unit.one_sentence || unit.question || "进入本知识点")}</small><em>${done ? "已完成 · 点击复习" : esc(unit.priority_label || "重点理解")}</em></span><span class="arrow">→</span></button>`;
    }).join("") || `<div class="empty">还没有知识单元。请从上方导入课程材料，或打开已有讲义。</div>`;
    document.querySelectorAll("[data-unit-index]").forEach((button) => button.addEventListener("click", () => { state.unitIndex = Number(button.dataset.unitIndex); state.view = "learn"; render(); }));
    $("startLearning").onclick = () => { state.unitIndex = 0; state.view = "learn"; render(); };
    $("resumeLearning").onclick = () => {
      const next = units().findIndex((unit) => !state.completed.has(unit.unit_id));
      state.unitIndex = next >= 0 ? next : 0;
      state.view = "learn";
      render();
    };
  }

  function renderLearn() {
    const unit = activeUnit();
    $("unitNav").innerHTML = units().map((item, index) => `<button class="nav-item ${index === state.unitIndex ? "is-active" : ""} ${state.completed.has(item.unit_id) ? "is-done" : ""}" data-nav-index="${index}" type="button"><span>${state.completed.has(item.unit_id) ? "✓" : index + 1}</span>${esc(item.title)}</button>`).join("");
    document.querySelectorAll("[data-nav-index]").forEach((button) => button.addEventListener("click", () => { state.unitIndex = Number(button.dataset.navIndex); render(); }));
    if (!unit) { $("lessonContent").innerHTML = `<div class="empty"><strong>还没有可讲解的知识单元</strong><p>请从上方导入课程材料，或打开已有讲义。</p></div>`; return; }
    const examples = list(unit.worked_examples).map((example) => `<section class="lesson-section example"><h3>${example.complete ? "完整例题" : "例题框架"}</h3><p class="question"><strong>题目：</strong>${lines(example.question)}</p><p>${lines(example.setup)}</p><ol>${list(example.steps).map((step) => `<li>${lines(step)}</li>`).join("")}</ol><p class="answer"><strong>答案：</strong>${lines(example.answer)}</p><p class="variation"><strong>换一个条件：</strong>${lines(example.variation)}</p>${example.complete ? "" : "<p class=\"small-note\">当前来源没有给出足够的具体条件；先掌握读题顺序，具体数值题需要补充材料或人工复核。</p>"}</section>`).join("");
    const mistakes = list(unit.misconceptions).length ? `<section class="lesson-section"><h3>最容易错在哪里</h3><div class="mistake-table">${list(unit.misconceptions).map((item) => `<div><b>错误想法</b><span>${lines(item.wrong)}</span></div><div><b>正确判断</b><span>${lines(item.correct)}</span></div><div><b>纠正动作</b><span>${lines(item.correction)}</span></div>`).join("")}</div></section>` : "";
    const practices = list(unit.practice_items).map((item, index) => `<div class="practice"><div class="practice-meta"><span>${practiceLabel(item.kind)}</span><small>${esc(item.difficulty || "练习")}</small></div><p><strong>练习 ${index + 1}：</strong>${lines(item.prompt)}</p><details><summary>我已经回答，查看答案与解析</summary><p><b>答案：</b>${lines(item.answer)}</p><p><b>解析：</b>${lines(item.explanation)}</p></details></div>`).join("");
    const hint = list(unit.step_chain)[0] || "先找出题目给出的对象和条件。";
    const done = state.completed.has(unit.unit_id);
    $("lessonContent").innerHTML = `<div class="lesson-top"><div><p class="eyebrow">知识点 ${state.unitIndex + 1} / ${units().length}${done ? " · 已完成" : ""}</p><h2>${esc(unit.title)}</h2></div><span class="priority">${esc(unit.priority_label || "重点理解")}</span></div><p class="grip">${lines(unit.one_sentence)}</p><section class="predict-box"><h3>先想 30 秒</h3><p>${lines(unit.question || "这个知识点要解决什么问题？")}</p><details><summary>需要提示时再打开</summary><p>可以先从“${lines(hint)}”开始，不必一开始就写完整答案。</p></details></section><section class="lesson-section"><h3>为什么要学</h3><p>${lines(unit.why)}</p>${unit.prerequisites?.length ? `<p class="small-note"><b>先修：</b>${unit.prerequisites.map(esc).join("；")}</p>` : ""}</section><section class="lesson-section"><h3>材料中看什么</h3><p>${lines(unit.material_explanation)}</p></section><section class="lesson-section teacher"><h3>教师补充</h3><p>${lines(unit.teacher_increment)}</p></section><section class="lesson-section bridge"><h3>导师补链：把逻辑补完整</h3><p>${lines(unit.tutor_bridge)}</p><ol class="steps">${list(unit.step_chain).map((step) => `<li>${lines(step)}</li>`).join("")}</ol></section>${examples}${mistakes}<section class="lesson-section"><h3>现在自己回答</h3><p class="small-note">先回答，再展开答案。三道题分别检查回忆、过程和迁移。</p>${practices || "<p>暂无练习题。</p>"}</section><div class="unit-footer"><span><b>学习重点：</b>${esc(unit.priority_label || "重点理解")}</span><span><b>评价信息：</b>${esc(unit.assessment_signal || "尚未观察到评价信号")}</span></div><div class="finish-box"><button class="${done ? "secondary-button" : "primary-button"}" id="markUnit" type="button">${done ? "已完成这个知识点" : "我完成了这个知识点"}</button><span class="muted">完成后会记住进度，方便下次继续。</span></div><details class="unit-sources"><summary>查看这个知识点的来源</summary>${renderSourceList(list(unit.source_refs))}</details><div class="lesson-nav"><button class="secondary-button" id="previousUnit" type="button" ${state.unitIndex === 0 ? "disabled" : ""}>← 上一个</button><button class="primary-button" id="nextUnit" type="button">${state.unitIndex === units().length - 1 ? "去课后复习" : "下一个知识点 →"}</button></div>`;
    $("markUnit").onclick = () => { markUnitComplete(); render(); };
    $("previousUnit").onclick = () => { if (state.unitIndex > 0) { state.unitIndex -= 1; render(); } };
    $("nextUnit").onclick = () => { markUnitComplete(); if (state.unitIndex < units().length - 1) { state.unitIndex += 1; render(); } else { state.view = "review"; render(); } };
  }

  function renderReview() {
    const route = state.guide.route || {};
    $("reviewChain").innerHTML = list(route.chain).map((item, index) => `<span><b>${index + 1}</b>${esc(item)}</span>`).join("");
    const done = completionCount();
    $("reviewItems").innerHTML = `<p class="review-progress">已完成 ${done}/${units().length} 个知识点。答案展开后，回到错题对应的知识点再看一遍。</p>` + (list(state.guide.review_items).map((item, index) => `<article class="review-card card"><p class="eyebrow">${practiceLabel(item.kind)} · 复习题 ${index + 1}</p><h3>${lines(item.prompt)}</h3><details><summary>我已经回答，查看答案</summary><p><b>答案：</b>${lines(item.answer)}</p><p><b>解析：</b>${lines(item.explanation)}</p><button class="link-button" data-review-unit="${esc(item.unit_id || "")}" type="button">回到对应知识点 →</button></details></article>`).join("") || `<div class="empty">暂无复习题。</div>`);
    document.querySelectorAll("[data-review-unit]").forEach((button) => button.addEventListener("click", () => { const index = units().findIndex((unit) => unit.unit_id === button.dataset.reviewUnit); if (index >= 0) { state.unitIndex = index; state.view = "learn"; render(); } }));
  }

  function renderSourceList(rows) {
    return rows.length ? `<ul>${rows.map((source) => `<li><span class="source-label">${esc(source.label || "来源")}</span><span>${esc(sourceLocation(source))}</span>${source.quote ? `<small>${lines(source.quote)}</small>` : ""}</li>`).join("")}</ul>` : "<p class=\"muted\">暂无可定位来源。</p>";
  }

  function renderSources() {
    const report = state.guide.report || {};
    $("sourceSummary").innerHTML = `<div><b>生成状态</b><span>${esc(report.status || "未知")}</span></div><div><b>页面文字覆盖</b><span>${report.covered_pages ?? 0} / ${report.total_pages ?? 0}</span></div><div><b>需要视觉复核</b><span>${report.visual_review_pages ?? 0} 页</span></div><div><b>时间片段已对齐</b><span>${report.aligned_segments ?? 0} / ${report.total_segments ?? 0}</span></div><div><b>课堂补充片段</b><span>${report.supplement_segments ?? 0}</span></div>`;
    $("sourceList").innerHTML = renderSourceList(list(state.guide.source_index));
  }

  function switchView(view) {
    state.view = view;
    ["route", "learn", "review"].forEach((name) => { $(`${name}View`).hidden = name !== view; });
    document.querySelectorAll(".view-button").forEach((button) => button.classList.toggle("is-active", button.dataset.view === view));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function loadGuide(guide, kind = "file") {
    if (!guide || typeof guide !== "object") throw new Error("讲义 JSON 必须是对象");
    if (guide.guide_kind !== "student-study-guide") throw new Error("这不是 student-study-guide；请先运行 study generate");
    state.guide = guide; state.unitIndex = 0; state.sourceKind = kind; readProgress(); setStatus(kind === "demo" ? "内置演示" : "本地讲义", kind); render();
  }

  async function boot() {
    document.querySelectorAll(".view-button").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
    $("guideFile").addEventListener("change", (event) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = () => { try { loadGuide(JSON.parse(reader.result), "file"); } catch (error) { setStatus(error.message, "error"); } }; reader.readAsText(file); });
    $("generateButton").addEventListener("click", async () => {
      const files = Array.from($("sourceFiles").files || []);
      if (!files.length) { $("uploadMessage").textContent = "请先选择至少一个课件、转写或音频文件。"; return; }
      $("generateButton").disabled = true; $("uploadMessage").textContent = "正在读取材料并生成学习草稿……";
      try {
        const payload = await Promise.all(files.map((file) => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve({ name: file.name, data: String(reader.result).split(",")[1] || "" }); reader.onerror = reject; reader.readAsDataURL(file); })));
        const response = await fetch("api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ files: payload }) });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "生成失败");
        loadGuide(result.guide, "file");
        $("uploadMessage").textContent = "已生成。你可以从学习路线开始。";
      } catch (error) { $("uploadMessage").textContent = `生成失败：${error.message}。请检查文件格式，或打开已有讲义。`; setStatus("生成失败", "error"); }
      finally { $("generateButton").disabled = false; }
    });
    try { const response = await fetch("study-guide.json", { cache: "no-store" }); if (!response.ok) throw new Error("没有本地讲义"); loadGuide(await response.json(), "file"); } catch (_) { loadGuide(demoGuide, "demo"); }
  }

  boot();
})();
