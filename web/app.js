(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const list = (value) => Array.isArray(value) ? value : [];
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const lines = (value) => esc(value).replace(/\n/g, "<br>");
  const P = window.StudyProgress;
  const emptyGuide = {title: "把这节课的材料放进来", units: [], route: {}, source_index: [], generation_report: {status: "needs-content"}};
  const state = {guide: emptyGuide, view: "route", index: 0, description: null, progress: null, revision: 0, serverSave: false, job: null, files: [], loading: 0};
  const units = () => list(state.guide.units);
  const active = () => units()[state.index];
  const done = (unit) => !!state.progress?.units[unit.unit_id]?.completed;
  let saveTimer, scrollTimer, jobTimer, saving = false, saveAgain = false, restoring = false;

  async function request(path, options = {}) {
    const response = await fetch(path, {cache: "no-store", ...options});
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.error || "暂时无法完成操作"); error.status = response.status; error.data = data; throw error; }
    return data;
  }
  const post = (path, value) => request(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(value)});
  function status(text, kind = "file") { $("sourceStatus").dataset.kind = kind; $("sourceStatusText").textContent = text; }
  function localSave() {
    if (!state.progress) return;
    try { localStorage.setItem(`mst-progress-v2:${state.description.key}`, JSON.stringify(state.progress)); }
    catch (_) { $("saveStatus").textContent = "浏览器无法保存；请保持本地服务开启，等待记录保存到本机。"; }
  }
  function save() {
    localSave();
    clearTimeout(saveTimer);
    if (state.serverSave) saveTimer = setTimeout(saveServer, 500);
  }
  async function saveServer() {
    if (!state.serverSave || !state.progress) return;
    if (saving) { saveAgain = true; return; }
    saving = true;
    const key = state.description.key;
    const snapshot = JSON.stringify(state.progress);
    try {
      const result = await post(`api/progress/${key}`, {revision: state.revision, progress: JSON.parse(snapshot)});
      if (state.description.key === key) {
        state.revision = result.revision;
        $("saveStatus").textContent = "阅读位置和练习草稿已保存在本机";
        if (JSON.stringify(state.progress) !== snapshot) saveAgain = true;
      }
    } catch (error) {
      if (state.description?.key === key) {
        if ([400,403,409].includes(error.status)) state.serverSave = false;
        $("saveStatus").textContent = error.status ? `${error.message} 本页草稿仍保留在浏览器。` : "本机服务暂时不可用；记录保留在此浏览器，正在重新连接。";
        if (!error.status) { clearTimeout(saveTimer); saveTimer = setTimeout(saveServer, 3000); }
      }
    } finally {
      saving = false;
      if (saveAgain) { saveAgain = false; save(); }
    }
  }
  function remember() {
    if (!state.progress || restoring) return;
    P.visit(state.progress, state.description, state.view, active()?.unit_id, window.scrollY);
    save();
  }
  function navigate(view, index = state.index, scroll = null) {
    remember();
    if (units().length) $("materialPanel").open = false;
    state.view = view;
    state.index = Math.max(0, Math.min(index, Math.max(0, units().length - 1)));
    render();
    restoring = true;
    requestAnimationFrame(() => {
      const target = view === "learn" ? $("lessonContent") : view === "review" ? $("reviewView") : null;
      window.scrollTo({top: scroll ?? (target ? target.getBoundingClientRect().top + window.scrollY - 12 : 0), behavior: "instant"});
      if (target) { target.tabIndex = -1; target.focus({preventScroll:true}); }
      restoring = false;
      remember();
    });
  }
  function practiceLabel(kind) { return ({retrieval: "回忆", process: "过程", transfer: "迁移", comparison: "对比"}[kind] || "练习"); }
  function practice(item, index, review = false) {
    const key = P.practiceKey(item, index);
    const draft = state.progress?.drafts[key]?.text || "";
    return `<article class="${review ? "review-card card" : "practice"}"><div class="practice-meta"><span>${practiceLabel(item.kind)}</span><small>${esc(item.difficulty)}</small></div><p><strong>${review ? "复习题" : "练习"} ${index + 1}：</strong>${lines(item.prompt)}</p><label class="answer-label">先写下你的回答<textarea rows="3" maxlength="20000" data-answer="${esc(key)}" placeholder="用自己的话回答，草稿会自动保存">${esc(draft)}</textarea></label><details><summary>查看答案与解析</summary><p><b>答案：</b>${lines(item.answer)}</p><p><b>解析：</b>${lines(item.explanation)}</p>${review ? `<button class="link-button" data-return-unit="${esc(item.unit_id)}" type="button">回到对应知识点 →</button>` : ""}</details></article>`;
  }
  function timestamp(value) {
    const seconds = String(value).split(":").reverse().reduce((sum, part, i) => sum + Number(part) * 60 ** i, 0);
    if (!Number.isFinite(seconds) || seconds < 0) return String(value);
    const whole = Math.floor(seconds);
    const fraction = Math.round((seconds - whole) * 1000);
    return [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60].map((part) => String(part).padStart(2, "0")).join(":") + (fraction ? `.${String(fraction).padStart(3,"0").replace(/0+$/,"")}` : "");
  }
  function sources(rows) {
    return rows.length ? `<ul>${rows.map((source) => {
      const location = source.page != null ? `第 ${source.page} 页` : source.start != null ? `${timestamp(source.start)}${source.end != null ? `–${timestamp(source.end)}` : " 起（结束未标注）"}` : "待定位";
      const prefix = state.guide._local_run_id ? `/api/jobs/${encodeURIComponent(state.guide._local_run_id)}/assets/` : "/assets/";
      const image = source.image_path && !state.localGuide ? `<small><a href="${prefix}${String(source.image_path).split("/").map(encodeURIComponent).join("/")}" target="_blank" rel="noopener">查看页面图像</a></small>` : "";
      return `<li><span class="source-label">${esc(source.label || "材料依据")}</span>${esc(location)}${image}${source.quote ? `<small>${lines(source.quote)}</small>` : ""}</li>`;
    }).join("")}</ul>` : '<p class="muted">暂无可定位来源。</p>';
  }
  function render() {
    const guide = state.guide, route = guide.route || {}, report = guide.generation_report || {};
    const count = units().filter(done).length, total = units().length;
    $("guideTitle").textContent = guide.title || "自学讲义";
    $("heroCopy").textContent = total ? "先理解，再用例题和练习检查自己。随时可以退出，下次接着学。" : "先选课件和教师转写，生成后从学习路线开始。";
    $("draftNotice").hidden = !total || report.status === "complete";
    $("draftText").textContent = `讲义内容仍需核验。${report.visual_review_pages ? `${report.visual_review_pages} 页图示或公式待复核。` : ""}${report.pending_segments ? `${report.pending_segments} 段语音未配准，未加入本课讲解。` : ""}已列出的框架和待补内容不能代替完整课程。`;
    $("centralQuestion").textContent = route.central_question || "导入后显示本课要解决的问题";
    $("estimatedTime").textContent = route.estimated_minutes ? `${route.estimated_minutes} 分钟` : "—";
    $("outcomes").innerHTML = list(route.outcomes).map((item) => `<li>${lines(item)}</li>`).join("");
    $("prerequisites").innerHTML = list(route.prerequisites).map((item) => `<li>${lines(item)}</li>`).join("");
    $("unitCount").textContent = `${total} 个知识单元`;
    $("progressBar").style.width = total ? `${Math.round(count / total * 100)}%` : "0%";
    $("progressText").textContent = total ? `${count}/${total} 个知识点已标记完成` : "尚未开始";
    $("startLearning").disabled = !total;
    $("resumeLearning").hidden = !state.progress?.reading;
    $("routeCards").innerHTML = units().map((unit, index) => `<button class="unit-card ${done(unit) ? "is-done" : ""}" data-unit="${index}" type="button"><span class="unit-number">${done(unit) ? "✓" : index + 1}</span><span><strong>${esc(unit.title)}</strong><small>${esc(unit.one_sentence || unit.question)}</small><em>${done(unit) ? "已标记完成 · 点击复习" : esc(unit.priority_label || "重点理解")}</em></span><span class="arrow">→</span></button>`).join("") || '<div class="empty">选择上方的材料，开始建立这节课的讲义。</div>';
    renderUnit();
    $("reviewChain").innerHTML = list(route.chain).map((item, i) => `<span><b>${i + 1}</b>${esc(item)}</span>`).join("");
    $("reviewItems").innerHTML = list(guide.review_items).map((item, i) => practice(item, i, true)).join("") || '<p class="empty">暂无复习题。</p>';
    const statusLabel = {complete: "内容检查已通过（仍需教学验收）", draft: "教学草稿", "needs-content": "等待补充内容"}[report.status] || "待检查";
    $("sourceSummary").innerHTML = [["生成状态",statusLabel],["页面文字覆盖",`${report.covered_pages || 0} / ${report.total_pages || 0}`],["图示待复核",`${report.visual_review_pages || 0} 页`],["教师片段已对齐",`${report.aligned_segments || 0} / ${report.total_segments || 0}`],["语音配对待确认",report.pending_segments || 0]].map(([label,value]) => `<div><b>${label}</b><span>${esc(value)}</span></div>`).join("") + list(report.warnings).map((warning) => `<p>${lines(warning)}</p>`).join("");
    $("sourceList").innerHTML = sources(list(guide.source_index));
    ["route", "learn", "review"].forEach((view) => { $(`${view}View`).hidden = view !== state.view; });
    document.querySelectorAll(".view-button").forEach((button) => button.classList.toggle("is-active", button.dataset.view === state.view));
  }
  function renderUnit() {
    const unit = active();
    $("unitNav").innerHTML = units().map((item, index) => `<button class="nav-item ${index === state.index ? "is-active" : ""} ${done(item) ? "is-done" : ""}" data-unit="${index}" type="button"><span>${done(item) ? "✓" : index + 1}</span>${esc(item.title)}</button>`).join("");
    if (!unit) { $("lessonContent").innerHTML = '<p class="empty">导入材料后，这里会显示精讲。</p>'; return; }
    const section = (title, body, className = "") => `<section class="lesson-section ${className}"><h3>${title}</h3>${body}</section>`;
    const examples = list(unit.worked_examples).map((example) => section(example.complete ? "完整例题" : "例题待补充", `<p class="question"><b>题目：</b>${lines(example.question)}</p><p>${lines(example.setup)}</p><ol>${list(example.steps).map((step) => `<li>${lines(step)}</li>`).join("")}</ol><p class="answer"><b>答案：</b>${lines(example.answer)}</p><p class="variation"><b>换一个条件：</b>${lines(example.variation)}</p>`, "example")).join("");
    const mistakes = list(unit.misconceptions).map((item) => `<div><b>错误想法</b><span>${lines(item.wrong)}</span></div><div><b>正确判断</b><span>${lines(item.correct)}</span></div><div><b>纠正动作</b><span>${lines(item.correction)}</span></div>`).join("");
    $("lessonContent").innerHTML = `<div class="lesson-top"><div><p class="eyebrow">知识点 ${state.index + 1} / ${units().length}</p><h2>${esc(unit.title)}</h2></div><span class="priority">${esc(unit.priority_label)}</span></div><p class="grip">${lines(unit.one_sentence)}</p><section class="predict-box"><h3>先想一想</h3><p>${lines(unit.question)}</p><details><summary>需要提示时再打开</summary><p>${lines(list(unit.step_chain)[0])}</p></details></section>${section("为什么要学", `<p>${lines(unit.why)}</p><p class="small-note">先修：${list(unit.prerequisites).map(esc).join("；") || "材料尚未列明"}</p>`)}${section("材料中看什么", `<p>${lines(unit.material_explanation)}</p>`)}${section("教师补充", `<p>${lines(unit.teacher_increment)}</p>`, "teacher")}${section("导师补链：把逻辑补完整", `<p>${lines(unit.tutor_bridge)}</p><ol class="steps">${list(unit.step_chain).map((step) => `<li>${lines(step)}</li>`).join("")}</ol>`, "bridge")}${examples}${mistakes ? section("最容易错在哪里", `<div class="mistake-table">${mistakes}</div>`) : ""}${section("现在自己回答", list(unit.practice_items).map((item, i) => practice({...item, unit_id: unit.unit_id}, i)).join("") || "<p>练习仍待补充。</p>")}<div class="unit-footer"><span>评价信息：${esc(unit.assessment_signal || "尚未观察到评价信号")}</span></div><div class="finish-box"><button class="secondary-button" id="markUnit" type="button">${done(unit) ? "撤销完成标记" : "我完成了这个知识点"}</button><span class="muted">翻到下一页不会自动标为完成。</span></div><details class="unit-sources"><summary>查看这个知识点的来源</summary>${sources(list(unit.source_refs))}</details><div class="lesson-nav"><button class="secondary-button" id="previousUnit" ${state.index === 0 ? "disabled" : ""} type="button">← 上一个</button><button class="primary-button" id="nextUnit" type="button">${state.index === units().length - 1 ? "去课后复习" : "下一个知识点 →"}</button></div>`;
    $("lessonContent").insertAdjacentHTML("afterbegin", '<button class="link-button" data-view="route" type="button">← 返回学习路线</button>');
    $("markUnit").onclick = () => { const scroll = window.scrollY; P.complete(state.progress, state.description, unit.unit_id, !done(unit)); save(); render(); window.scrollTo(0, scroll); };
    $("previousUnit").onclick = () => navigate("learn", state.index - 1);
    $("nextUnit").onclick = () => state.index < units().length - 1 ? navigate("learn", state.index + 1) : navigate("review");
  }
  async function loadGuide(guide, local = false, keepMaterialsOpen = false) {
    if (guide?.guide_kind !== "student-study-guide" || !Array.isArray(guide.units)) throw new Error("请选择生成的自学讲义文件；原课件请从下方导入。");
    remember();
    const loading = ++state.loading;
    const description = await P.describe(guide);
    let previous, revision = 0, serverSave = false;
    try { previous = JSON.parse(localStorage.getItem(`mst-progress-v2:${description.key}`) || "null"); } catch (_) { /* empty or unavailable storage */ }
    try {
      const saved = await request(`api/progress/${description.key}`);
      revision = saved.revision; serverSave = true;
      if ((saved.progress?.updated_at || 0) > (previous?.updated_at || 0)) previous = saved.progress;
    } catch (_) { /* Static file use can still save in the browser. */ }
    if (loading !== state.loading) return;
    state.guide = guide; state.description = description; state.localGuide = local;
    state.progress = P.reconcile(description, previous);
    state.revision = revision; state.serverSave = serverSave;
    const last = state.progress.last;
    state.view = last?.view || "route";
    state.index = Math.max(0, units().findIndex((unit) => unit.unit_id === last?.unit_id));
    $("downloads").hidden = local || !serverSave;
    $("jsonDownload").hidden = local || !serverSave;
    document.querySelectorAll("a[data-export]").forEach((link) => { link.href = `api/exports/${link.dataset.export}${guide._local_run_id ? `?run=${encodeURIComponent(guide._local_run_id)}` : ""}`; });
    $("saveStatus").textContent = serverSave ? "阅读位置和练习草稿会保存在本机" : "学习记录保存在当前浏览器；清除浏览器数据会移除记录。";
    status("本地讲义"); render();
    $("materialPanel").open = keepMaterialsOpen;
    restoring = true;
    requestAnimationFrame(() => { window.scrollTo(0, last?.scroll || 0); restoring = false; });
  }
  const stageOrder = [["inventory","材料处理"],["aligning","页面与讲解配对"],["writing","组织讲义"],["checking","内容检查"],["exporting","保存讲义"]];
  function showJob(job) {
    state.job = job;
    const busy = ["queued","running"].includes(job.status);
    if (busy || ["failed","interrupted"].includes(job.status)) $("materialPanel").open = true;
    $("generateButton").disabled = busy;
    $("retryJob").hidden = !["failed","interrupted"].includes(job.status);
    $("uploadMessage").textContent = job.message;
    $("jobStages").hidden = false;
    const stages = new Set(list(job.history).map((item) => item.stage));
    $("jobStages").innerHTML = stageOrder.map(([stage,label]) => `<li class="${stages.has(stage) ? "reached" : ""}">${esc(label)}</li>`).join("");
  }
  async function watchJob(job, showResult = true) {
    clearTimeout(jobTimer);
    showJob(job);
    if (["queued","running"].includes(job.status)) {
      jobTimer = setTimeout(async () => {
        try { const data = await request(`api/jobs/${job.job_id}`); await watchJob(data.job, true); }
        catch (_) { $("uploadMessage").textContent = "连接已断开。材料和生成记录仍在本机，正在重新连接……"; jobTimer = setTimeout(() => watchJob(job, true), 2500); }
      }, 900);
    } else if (job.status === "succeeded" && showResult) {
      await loadGuide(await request(`api/jobs/${job.job_id}/guide`), false, true);
    }
  }
  async function submit(retry = false) {
    $("materialPanel").open = true;
    $("generateButton").disabled = true; $("retryJob").disabled = true;
    $("uploadMessage").textContent = retry ? "正在重新提交已保存的材料……" : "正在将所选材料保存到本机……";
    try {
      let result;
      if (retry) result = await post(`api/jobs/${state.job.job_id}/retry`, {});
      else {
        if (!state.files.length) throw new Error("请先选择课件或教师转写。");
        if (state.files.reduce((sum,file) => sum + file.size, 0) > 100 * 1024 * 1024) throw new Error("本次材料超过 100 MB，请分课次导入。");
        const files = await Promise.all(state.files.map((file) => new Promise((resolve,reject) => {
          const reader = new FileReader(); reader.onload = () => resolve({name: file.name, data: String(reader.result).split(",")[1]}); reader.onerror = () => reject(new Error(`无法读取：${file.name}`)); reader.readAsDataURL(file);
        })));
        result = await post("api/jobs", {files, subject: $("subject").value});
      }
      await watchJob(result.job);
    } catch (error) {
      if (error.data?.job) await watchJob(error.data.job);
      else {
        $("uploadMessage").textContent = `${error.message} 已有讲义仍保留。`;
        $("generateButton").disabled = false;
      }
    } finally { $("retryJob").disabled = false; }
  }
  function selectFiles(files) {
    state.files = Array.from(files || []);
    $("selectedFiles").textContent = state.files.map((file) => file.name).join("、");
  }
  async function boot() {
    document.addEventListener("click", (event) => {
      const unit = event.target.closest("[data-unit]");
      const view = event.target.closest("[data-view]");
      const back = event.target.closest("[data-return-unit]");
      if (unit) navigate("learn", Number(unit.dataset.unit));
      if (view) navigate(view.dataset.view);
      if (back) { const index = units().findIndex((item) => item.unit_id === back.dataset.returnUnit); if (index >= 0) navigate("learn", index); }
    });
    document.addEventListener("input", (event) => {
      if (event.target.matches("[data-answer]")) { P.answer(state.progress, state.description, event.target.dataset.answer, event.target.value); save(); }
    });
    $("startLearning").onclick = () => navigate("learn", 0);
    $("resumeLearning").onclick = () => { const last = {...state.progress.reading}; navigate(last.view, Math.max(0, units().findIndex((unit) => unit.unit_id === last.unit_id)), last.scroll); };
    $("guideFile").onchange = async (event) => { const file = event.target.files?.[0]; if (file) try { await loadGuide(JSON.parse(await file.text()), true); } catch (error) { status(error.message,"error"); } };
    $("sourceFiles").onchange = (event) => selectFiles(event.target.files);
    $("generateButton").onclick = () => submit();
    $("retryJob").onclick = () => submit(true);
    $("uploadBox").addEventListener("dragover", (event) => { event.preventDefault(); $("uploadBox").classList.add("is-dragging"); });
    $("uploadBox").addEventListener("dragleave", () => $("uploadBox").classList.remove("is-dragging"));
    $("uploadBox").addEventListener("drop", (event) => { event.preventDefault(); $("uploadBox").classList.remove("is-dragging"); selectFiles(event.dataTransfer.files); });
    window.addEventListener("scroll", () => { clearTimeout(scrollTimer); scrollTimer = setTimeout(remember, 250); }, {passive:true});
    window.addEventListener("pagehide", () => {
      remember();
      if (state.serverSave && state.progress && !saving) {
        const body = JSON.stringify({revision: state.revision, progress: state.progress});
        if (body.length < 60000) fetch(`api/progress/${state.description.key}`, {method:"POST", headers:{"Content-Type":"application/json"}, body, keepalive:true}).catch(() => {});
      }
    });
    document.addEventListener("visibilitychange", () => { if (document.hidden) { remember(); saveServer(); } });
    try { await loadGuide(await request("study-guide.json")); }
    catch (error) { state.guide = emptyGuide; render(); status("等待导入"); if (error.status && error.status !== 404) $("uploadMessage").textContent = error.message; }
    try { const result = await request("api/jobs/latest"); if (result.job) await watchJob(result.job, false); }
    catch (_) { /* Opening an exported/static guide needs no job server. */ }
  }
  boot();
})();
