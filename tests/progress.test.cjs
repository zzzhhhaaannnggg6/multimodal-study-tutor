const {test} = require("node:test");
const assert = require("node:assert/strict");
const P = require("../web/progress.js");
const guide = () => ({lesson_id: `course::${"a".repeat(64)}`, subject:"generic", title:"同名课程", units:[{unit_id:"u1", title:"第一节", practice_items:[{practice_id:"p1", unit_id:"u1", prompt:"问题", answer:"答案"}]},{unit_id:"u2", title:"第二节"}]});

test("reading and Unicode answers survive serialization; navigating does not complete a unit", async () => {
  const description = await P.describe(guide());
  const record = P.reconcile(description, null);
  P.visit(record, description, "learn", "u1", 730);
  P.answer(record, description, "u1::p1", "中文 x²\naddi x5, x0, 10");
  const restored = P.reconcile(description, JSON.parse(JSON.stringify(record)));
  assert.equal(restored.last.scroll, 730);
  assert.equal(restored.drafts["u1::p1"].text, "中文 x²\naddi x5, x0, 10");
  assert.equal(restored.units.u1.completed, undefined);
  P.visit(restored, description, "route", "u1", 0);
  assert.equal(restored.reading.scroll, 730);
});

test("a changed unit loses stale completion and answers while unchanged units retain progress", async () => {
  const original = guide(), description = await P.describe(original), record = P.reconcile(description);
  P.complete(record, description, "u1"); P.complete(record, description, "u2");
  P.answer(record, description, "u1::p1", "旧答案");
  P.visit(record, description, "learn", "u1", 800);
  original.units[0].title = "修订后的讲解";
  const restored = P.reconcile(await P.describe(original), record);
  assert.equal(restored.units.u1, undefined);
  assert.equal(restored.units.u2.completed, true);
  assert.deepEqual(restored.drafts, {});
  assert.equal(restored.last, null);
  assert.equal(restored.reading, null);
});

test("same titles and reused internal IDs do not mix different source courses", async () => {
  const first = guide(), second = guide();
  delete first.lesson_id; delete second.lesson_id;
  first.source_index = [{ref:"p1", quote:"第一门课"}];
  second.source_index = [{ref:"p1", quote:"另一门课"}];
  const a = await P.describe(first), b = await P.describe(second);
  assert.notEqual(a.key, b.key);
  const record = P.reconcile(a); P.complete(record,a,"u1");
  assert.deepEqual(P.reconcile(b,record).units, {});
  assert.deepEqual(P.reconcile(a,["u1"]).units, {}); // Unsafe old title-based arrays are not silently inherited.
});
