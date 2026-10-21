/* Course-scoped progress; completion is invalidated when teaching content changes. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudyProgress = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function stable(value) {
    if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
    if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`;
    return JSON.stringify(value) ?? "null";
  }
  async function digest(value) {
    const crypto = globalThis.crypto || require("node:crypto").webcrypto;
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(stable(value)));
    return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  function practiceKey(item, index = 0) { return `${item.unit_id || "review"}::${item.practice_id || index}`; }
  async function describe(guide) {
    const units = guide.units || [];
    const sources = guide.source_index || [];
    const identity = /^course::[0-9a-f]{64}$/.test(guide.lesson_id || "")
      ? guide.lesson_id : {id: guide.lesson_id, subject: guide.subject, sources: sources.length ? sources : units};
    const revisions = Object.fromEntries(await Promise.all(units.map(async (unit) => [unit.unit_id, await digest(unit)])));
    const practices = {};
    await Promise.all([...units.flatMap((unit) => (unit.practice_items || []).map((item) => ({...item, unit_id: unit.unit_id}))), ...(guide.review_items || [])].map(async (item, index) => {
      const {prompt, answer, explanation, kind} = item;
      practices[practiceKey(item, index)] = await digest({prompt, answer, explanation, kind, revision: revisions[item.unit_id]});
    }));
    return {key: await digest(identity), revisions, practices};
  }
  function reconcile(description, previous) {
    const fresh = {version: 2, course_key: description.key, units: {}, drafts: {}, last: null, reading: null, updated_at: 0};
    if (!previous || previous.version !== 2 || previous.course_key !== description.key) return fresh;
    for (const [id, revision] of Object.entries(description.revisions)) {
      if (previous.units?.[id]?.revision === revision) fresh.units[id] = {...previous.units[id]};
    }
    for (const [id, revision] of Object.entries(description.practices)) {
      const draft = previous.drafts?.[id];
      if (draft?.revision === revision && typeof draft.text === "string") fresh.drafts[id] = {...draft};
    }
    const last = previous.last;
    if (last && ["route", "learn", "review"].includes(last.view) && (last.view !== "learn" || fresh.units[last.unit_id])) fresh.last = {...last, scroll: Math.max(0, Number(last.scroll) || 0)};
    if (previous.reading?.view === "learn" && fresh.units[previous.reading.unit_id]) fresh.reading = {...previous.reading, scroll: Math.max(0, Number(previous.reading.scroll) || 0)};
    fresh.updated_at = Number(previous.updated_at) || 0;
    return fresh;
  }
  function visit(record, description, view, unitId, scroll) {
    if (description.revisions[unitId]) record.units[unitId] = {...record.units[unitId], revision: description.revisions[unitId]};
    record.last = {view, unit_id: unitId, scroll: Math.max(0, scroll || 0)};
    if (view === "learn") record.reading = {...record.last};
    record.updated_at = Date.now();
  }
  function complete(record, description, unitId, done = true) {
    record.units[unitId] = {revision: description.revisions[unitId], completed: done};
    record.updated_at = Date.now();
  }
  function answer(record, description, id, text) {
    if (!description.practices[id]) return;
    record.drafts[id] = {revision: description.practices[id], text: String(text).slice(0, 20000)};
    record.updated_at = Date.now();
  }
  return {describe, reconcile, visit, complete, answer, practiceKey};
});
