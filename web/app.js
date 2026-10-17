(() => {
  "use strict";

  const demoMap = {
    schema_version: "1.0",
    map_kind: "lesson-reconstruction",
    subject: "generic",
    profile: "generic",
    title: "从证据到机制",
    notes: { status: "demo", message: "公开脱敏演示地图" },
    pages: [
      { visual_id: "demo::p001", page: 1, title: "先看证据", status: "covered", text: "材料中直接可观察到什么？" },
      { visual_id: "demo::p002", page: 2, title: "再补机制", status: "covered", text: "中间机制如何把证据连接到结果？" },
      { visual_id: "demo::p003", page: 3, title: "最后做迁移", status: "covered", text: "条件变化时，结论是否仍成立？" }
    ],
    audio_segments: [
      { segment_id: "demo::s001", start: 12, end: 28, text: "先确定材料中能直接观察到的事实，再补上中间机制。", status: "aligned", alignment: { visual_ids: ["demo::p001"], unit_ids: ["demo::u001"], status: "aligned", confidence: "high" } },
      { segment_id: "demo::s002", start: 31, end: 52, text: "如果只记结论，不知道机制，换一个例子就容易失去方向。", status: "aligned", alignment: { visual_ids: ["demo::p002"], unit_ids: ["demo::u001"], status: "aligned", confidence: "high" } }
    ],
    units: [
      { unit_id: "demo::u001", title: "从证据到机制", visual_ids: ["demo::p001", "demo::p002", "demo::p003"], segment_ids: ["demo::s001", "demo::s002"], understanding_level: "U3", exam_evidence_level: "E1", logic_chain: "观察证据 -> 识别机制 -> 检查结果", learner_action: "能在新例子中指出证据、机制和结果。", representative_example: "把一个新案例拆成可观察事实和解释步骤。", transfer_question: "如果中间机制改变，结论还成立吗？", status: "verified" }
    ],
    claims: [
      { claim_id: "demo::c001", unit_id: "demo::u001", text: "解释不能跳过证据到结果之间的机制。", visual_ids: ["demo::p002"], segment_ids: ["demo::s001"], source_labels: ["材料·p.2", "课堂转述·00:12–00:28"], understanding_level: "U3", exam_evidence_level: "E1", status: "verified", sources: [{ kind: "material", ref: "demo::p002", page: 2, verified: true, status: "verified" }, { kind: "classroom_transcript", ref: "demo::s001@00:12–00:28", start: 12, end: 28, quote: "先确定材料中能直接观察到的事实，再补上中间机制。", verified: true, status: "verified" }] }
    ],
    review_items: [{ review_id: "demo::r001", unit_id: "demo::u001", prompt: "请用一句话说明为什么不能从证据直接跳到结论。", answer: "因为缺少机制，无法解释条件如何产生结果。", answer_hidden: true }]
  };

  const state = { map: demoMap, mode: "understanding", pageIndex: 0, unitId: null, claimId: null, segmentId: null, sourceKind: "demo" };
  const $ = (id) => document.getElementById(id);
  const list = (value) => Array.isArray(value) ? value : [];
  const pages = () => list(state.map.pages || state.map.visual_sources || state.map.visual_frames);
  const segments = () => list(state.map.audio_segments || state.map.speech_segments || state.map.media_segments);
  const units = () => list(state.map.units || state.map.knowledge_units);
  const claims = () => list(state.map.claims);
  const reviews = () => list(state.map.review_items || state.map.reviews);
  const unitId = (unit) => unit && (unit.unit_id || unit.id);
  const pageId = (page) => page && (page.visual_id || page.page_id || page.slide_id || page.id);
  const segmentId = (segment) => segment && (segment.segment_id || segment.id);
  const claimId = (claim) => claim && (claim.claim_id || claim.id);
  const activeUnit = () => units().find((unit) => unitId(unit) === state.unitId) || units()[0];
  const activePage = () => pages()[state.pageIndex] || pages()[0];

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
  }

  function seconds(value) {
    if (typeof value === "number") return value;
    if (value == null || value === "") return null;
    const parts = String(value).replace(",", ".").split(":").map(Number);
    if (parts.some(Number.isNaN)) return null;
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return parts[0];
  }

  function clock(value) {
    const total = seconds(value);
    if (total == null) return "—";
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    return `${h ? `${String(h).padStart(2, "0")}:` : ""}${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function sourceType(evidence) {
    const kind = String(evidence?.kind || "pending").toLowerCase();
    if (kind.includes("teacher") || kind.includes("transcript") || kind.includes("audio")) return "teacher";
    if (kind.includes("tutor") || kind.includes("synthesis") || kind.includes("inference")) return "inference";
    if (kind.includes("material") || kind.includes("slide") || kind.includes("reading")) return "material";
    return "pending";
  }

  function setStatus(label, kind = "demo") {
    $("sourceStatus").dataset.kind = kind;
    $("sourceStatusText").textContent = label;
  }

  function render() {
    const pageRows = pages();
    const unit = activeUnit();
    if (unit && !state.unitId) state.unitId = unitId(unit);
    $("projectTitle").textContent = state.map.title || `${state.map.subject || "学习"} · 课堂地图`;
    $("projectSummary").textContent = state.map.notes?.message || "课件是视觉主线，教师语音补充重点、逻辑与评价信号。";
    $("statPages").textContent = pageRows.length;
    $("statUnits").textContent = units().length;
    $("statEvidence").textContent = claims().reduce((sum, claim) => sum + list(claim.sources || claim.evidence).length, 0);
    $("statFocus").textContent = unit?.title || "等待选择";
    $("statFocusNote").textContent = state.mode === "extraction" ? "先回答问题，再展开答案" : "选择页面、单元或时间片段";
    renderPages(pageRows);
    renderUnit(unit);
    renderEvidence(unit);
    renderTimeline();
    document.querySelectorAll(".mode-button").forEach((button) => {
      const active = button.dataset.mode === state.mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function renderPages(rows) {
    const page = activePage();
    $("pageCounter").textContent = rows.length ? `${state.pageIndex + 1} / ${rows.length}` : "— / —";
    $("slideStage").innerHTML = page ? `<div class="slide-art"><span class="slide-number">PAGE ${escapeHtml(page.page ?? page.source_page ?? state.pageIndex + 1)}</span><div class="slide-title">${escapeHtml(page.title || "未命名页面")}</div><div class="slide-rule"></div><div class="slide-lines"><i></i><i></i><i></i></div><div class="slide-diagram"><span class="diagram-node">证据</span><span class="diagram-arrow"></span><span class="diagram-node">机制</span></div></div>` : `<div class="empty-state compact"><span class="empty-symbol">□</span><strong>还没有视觉页面</strong><p>加载 lesson-map JSON，或先查看内置演示。</p></div>`;
    $("slidePageLabel").textContent = page ? `P.${page.page ?? page.source_page ?? state.pageIndex + 1}` : "P.—";
    $("slideTitle").textContent = page?.title || "等待页面";
    $("sourceMeta").innerHTML = page ? `<span><strong>页面状态</strong> ${escapeHtml(page.status || "待确认")}</span><span>${escapeHtml(page.text || page.note || "视觉内容已纳入课堂地图。")}</span>` : "";
    $("pageStrip").innerHTML = rows.map((row, index) => `<button class="page-thumb ${index === state.pageIndex ? "is-active" : ""}" data-page-index="${index}" type="button"><span class="page-thumb-number">P.${escapeHtml(row.page ?? row.source_page ?? index + 1)}</span><span class="page-thumb-title">${escapeHtml(row.title || "未命名")}</span></button>`).join("");
    document.querySelectorAll("[data-page-index]").forEach((button) => button.addEventListener("click", () => { state.pageIndex = Number(button.dataset.pageIndex); const row = rows[state.pageIndex]; const match = units().find((item) => list(item.visual_ids).includes(pageId(row))); if (match) state.unitId = unitId(match); render(); }));
  }

  function renderUnit(unit) {
    $("lessonKicker").textContent = state.mode === "extraction" ? "闭卷提取" : "知识单元";
    $("lessonHeading").textContent = unit?.title || "等待课堂重建";
    $("lessonPriority").textContent = unit ? `${unit.understanding_level || "U?"} · ${unit.exam_evidence_level || "E?"}` : "—";
    if (!unit) { $("lessonBody").innerHTML = `<div class="empty-state"><span class="empty-symbol">✦</span><strong>尚未生成知识单元</strong><p>加载一个包含 <code>units</code> 的 JSON。</p></div>`; $("claimsList").innerHTML = ""; $("claimsCount").textContent = "0 条"; return; }
    const chain = String(unit.logic_chain || "").split(/\s*(?:->|→)\s*/).filter(Boolean);
    const relatedClaims = claims().filter((claim) => claim.unit_id === unitId(unit));
    const review = reviews().find((item) => item.unit_id === unitId(unit));
    const answer = state.mode === "extraction" ? `<p class="recall-answer">答案：${escapeHtml(review?.answer || unit.learner_action || "暂无独立答案")}</p>` : "";
    $("lessonBody").innerHTML = state.mode === "extraction" ? `<div class="lesson-body"><div class="extraction-box"><h3>先提取，再核对</h3><p class="recall-prompt">${escapeHtml(review?.prompt || unit.transfer_question || "请复述这个知识单元的核心链条。")}</p>${answer}</div></div>` : `<div class="lesson-body"><p class="lesson-intro">${escapeHtml(unit.learner_action || unit.summary || "先把材料中的观察、机制和结果连起来。")}</p><div class="focus-callout"><b>学习动作</b> 先看页面，再用课堂语音补齐逻辑链。</div><div class="lesson-columns"><div class="lesson-block"><h3>逻辑链</h3><ol class="chain">${(chain.length ? chain : [unit.logic_chain || "等待逻辑链"]).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></div><div class="lesson-block"><h3>例子 / 迁移</h3><p>${escapeHtml(unit.representative_example || unit.counterexample || unit.transfer_question || "暂无例子")}</p></div></div></div>`;
    $("claimsCount").textContent = `${relatedClaims.length} 条`;
    $("claimsList").innerHTML = relatedClaims.length ? relatedClaims.map((claim) => `<button class="claim-row ${claim.status === "pending" || claim.status === "unresolved" ? "pending" : ""} ${claimId(claim) === state.claimId ? "is-active" : ""}" data-claim-id="${escapeHtml(claimId(claim))}" type="button"><span class="claim-dot"></span><span class="claim-text">${escapeHtml(claim.text)}</span><span class="claim-meta">${escapeHtml(claim.exam_evidence_level || "E0")}</span></button>`).join("") : `<div class="empty-state compact"><strong>暂无主张</strong><p>生成课堂重建后，主张会在这里出现。</p></div>`;
    document.querySelectorAll("[data-claim-id]").forEach((button) => button.addEventListener("click", () => { state.claimId = button.dataset.claimId; const claim = claims().find((item) => claimId(item) === state.claimId); const p = pages().findIndex((item) => list(claim?.visual_ids).includes(pageId(item))); if (p >= 0) state.pageIndex = p; render(); }));
  }

  function renderEvidence(unit) {
    const related = claims().filter((claim) => claim.unit_id === unitId(unit));
    const evidence = related.flatMap((claim) => list(claim.sources || claim.evidence).map((item) => ({ ...item, claim })));
    const verified = evidence.filter((item) => item.verified || item.status === "verified").length;
    const ratio = evidence.length ? Math.round(verified / evidence.length * 100) : 0;
    $("evidenceScore").textContent = evidence.length ? `${ratio}%` : "—";
    $("coverageLabel").textContent = evidence.length ? `${verified}/${evidence.length}` : "—";
    $("coverageBar").style.width = `${ratio}%`;
    $("coverageNote").textContent = evidence.length ? "已验证证据优先显示；待确认项不会被隐藏。" : "选择一个知识单元查看其证据。";
    $("evidenceList").innerHTML = evidence.length ? evidence.map((item) => { const type = sourceType(item); return `<div class="evidence-group"><div class="evidence-row" data-evidence-ref="${escapeHtml(item.ref || item.source_id || "")}"><span class="evidence-type ${type}">${type === "teacher" ? "教师" : type === "inference" ? "补链" : type === "material" ? "材料" : "待定"}</span><span class="evidence-copy"><strong>${escapeHtml(item.quote || item.excerpt || item.ref || "未命名证据")}</strong><span>${escapeHtml(item.ref || item.source_id || item.locator || "定位待补充")} ${item.verified || item.status === "verified" ? "· 已核验" : "· 待确认"}</span></span></div></div>`; }).join("") : `<div class="empty-state compact"><span class="empty-symbol">⌁</span><strong>暂无证据</strong><p>每条主张都应能回到页面或课堂片段。</p></div>`;
  }

  function renderTimeline() {
    const rows = segments().filter((item) => seconds(item.start) != null || seconds(item.end) != null);
    if (!rows.length) { $("timelineEmpty").hidden = false; $("timelineScroll").hidden = true; $("segmentLabel").textContent = "未选择片段"; return; }
    $("timelineEmpty").hidden = true; $("timelineScroll").hidden = false;
    const max = Math.max(...rows.map((item) => seconds(item.end) ?? seconds(item.start) ?? 0), 1);
    const marks = 5;
    $("timelineRuler").innerHTML = Array.from({ length: marks + 1 }, (_, index) => `<span class="ruler-mark" style="left:${index / marks * 100}%">${clock(max * index / marks)}</span>`).join("");
    $("timelineTrack").innerHTML = rows.map((row) => { const start = seconds(row.start) ?? 0; const end = seconds(row.end) ?? start + 1; const left = start / max * 100; const width = Math.max((end - start) / max * 100, 1.2); return `<button class="timeline-segment ${segmentId(row) === state.segmentId ? "is-active" : ""}" style="left:${left}%;width:${width}%" data-segment-id="${escapeHtml(segmentId(row))}" title="${escapeHtml(row.text || "课堂片段")}" type="button"></button>`; }).join("");
    $("timelineCards").style.setProperty("--segment-count", rows.length);
    $("timelineCards").innerHTML = rows.map((row) => `<button class="timeline-card ${segmentId(row) === state.segmentId ? "is-active" : ""}" data-segment-card="${escapeHtml(segmentId(row))}" type="button"><time>${clock(row.start)}–${clock(row.end)}</time><strong>${escapeHtml(row.kind || "课堂片段")}</strong><p>${escapeHtml(row.text || "暂无转写文本")}</p></button>`).join("");
    const selectSegment = (id) => { state.segmentId = id; const row = rows.find((item) => segmentId(item) === id); const match = units().find((item) => list(item.segment_ids).includes(id)); if (match) state.unitId = unitId(match); const p = pages().findIndex((item) => list(row?.alignment?.visual_ids).includes(pageId(item))); if (p >= 0) state.pageIndex = p; $("segmentLabel").textContent = row ? `${clock(row.start)} · ${row.text || "课堂片段"}` : "未选择片段"; render(); };
    document.querySelectorAll("[data-segment-id]").forEach((button) => button.addEventListener("click", () => selectSegment(button.dataset.segmentId)));
    document.querySelectorAll("[data-segment-card]").forEach((button) => button.addEventListener("click", () => selectSegment(button.dataset.segmentCard)));
  }

  function loadMap(map, kind = "file") {
    if (!map || typeof map !== "object") throw new Error("lesson-map 必须是 JSON 对象");
    state.map = map; state.pageIndex = 0; state.unitId = unitId(units()[0]); state.claimId = null; state.segmentId = null; state.sourceKind = kind;
    setStatus(kind === "file" ? "本地 lesson-map" : "演示地图", kind); render();
  }

  async function boot() {
    $("mapFile").addEventListener("change", (event) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = () => { try { loadMap(JSON.parse(reader.result), "file"); } catch (error) { setStatus(error.message, "error"); } }; reader.readAsText(file); });
    $("resetDemo").addEventListener("click", () => loadMap(demoMap, "demo"));
    $("emptyLoadDemo")?.addEventListener("click", () => loadMap(demoMap, "demo"));
    $("clearSelection").addEventListener("click", () => { state.segmentId = null; state.claimId = null; $("segmentLabel").textContent = "未选择片段"; render(); });
    document.querySelectorAll(".mode-button").forEach((button) => button.addEventListener("click", () => { state.mode = button.dataset.mode; render(); }));
    try { const response = await fetch("lesson-map.json", { cache: "no-store" }); if (response.ok) loadMap(await response.json(), "file"); else throw new Error("no local map"); } catch (_) { loadMap(demoMap, "demo"); }
  }

  boot();
})();
