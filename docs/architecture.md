# Architecture

The repository is intentionally split into four layers:

1. **Core contract** — `mst.models` describes portable source, alignment,
   knowledge, evidence and review records. `mst.validation` rejects claims that
   cannot be traced back to a source.
2. **Preparation** — `mst.ingest` records source metadata and hashes without
   editing original files. `mst.extract` reads PPT/PDF/transcript content,
   `mst.multimodal` records code/formula/diagram and speech-role signals, and
   `mst.alignment` makes conservative page/time candidates with confidence.
3. **Reconstruction** — `mst.reconstruct` creates the deterministic source
   scaffold. `mst.planning` groups source headings or checks an optional model
   course proposal; `mst.guide` then builds the student-facing guide with all
   page/time references attached. `mst.teaching` detects specific empty or
   repetitive teaching patterns, without certifying factual truth.
4. **Surfaces** — the CLI, local study route, Markdown/HTML exports, and Agent
   API consume the map or guide. The map stays evidence-first; the guide is
   readable without understanding internal IDs or U/E levels.

## Data flow

```text
source files -> project.json -> lesson-map.json -> study-guide.json -> Markdown/Web/Agent
                    |                |                 |
                 hashes          planning          quality checks
                                     |
                              course-plan.json
```

The map and guide are interchange artifacts. It is safe to regenerate derived
files, while source assets remain outside the public repository by default.

## Provider boundary

`ModelProvider.complete(system, user, response_format)` is the only model
surface required by the first release. `MockProvider` makes CI deterministic;
`OpenAIProvider` is optional and lazy-loaded. A future local model or another
host can implement the same protocol without changing the map schema.

`study generate` can run without a provider. It creates a traceable draft and
records missing teaching fields in `generation-report.json`; it never labels a
draft as a complete course. With a provider, the same guide contract is used
to enrich explanations, worked examples, misconceptions, and practice items.

When no knowledge units were supplied, generation first requests a whole-course
plan from an explicitly selected text provider. The plan includes observable
outcomes, external prerequisites, a short spine, original source assignments,
and a prerequisite graph. Each cited source needs a literal anchor from that
source. Every eligible page and speech segment must be assigned or explicitly
deferred, and aligned speech cannot be moved to unrelated pages. Unknown,
self-referential and cyclic prerequisites are rejected. Accepted temporary
unit IDs are replaced by hashes of subject, title and original source IDs, so
reordering and temporary-ID changes preserve identity; concept renaming can
still change IDs. Proposed plans remain unverified tutor suggestions.

Planning uses at most 160,000 characters of encoded source context and refuses
an oversized planning request before calling the provider; it never silently
truncates the course. A failed plan preserves a source-heading draft with a
diagnostic. Per-unit enrichment still runs separately with the selected
provider. The offline plan only merges explicit equal headings (including
continuations) within a deck, without inventing prerequisites. Generic example
headings stay separate. Large heading lists are not presented as a reconstructed
mainline. Supplied knowledge maps retain their units and use their own declared
dependency graph instead of requesting a new plan.

`derived/course-plan.json` records the current plan, anchors, dependencies,
source dispositions and fingerprint; it is `null` when supplied units were
used, preventing a stale plan from a previous generation. The guide carries
the same plan and a short generation-report summary. HTML, Markdown and the
web reader link prerequisite units; deferred material explains its limitation
in the source appendix. These are local derived artifacts, not public examples.

## Current boundaries and next extensions

The deterministic signal layer can detect structure in extracted text and PPTX
shape XML, but it does not claim to read a screenshot, recognize an equation
from pixels, or hear an audio file without a speech provider. Pages with images,
formulas or connectors receive a visible visual-review flag; transcript
segments without adequate source-text anchors remain pending. A supplement
must be explicitly identified; absence of a match is not evidence that speech
belongs to the same lesson.

DOCX extraction groups separate timestamp paragraphs with their speech and
records raw paragraph positions, clock resets, and inferred boundaries.
Alignment ignores generated visual summaries, bare numbers and page markers;
it normalizes a small bilingual computer-systems glossary and coalesces
overlapping Chinese bigrams before counting independent anchors. A transcript
with little page support is held for pairing review. These are conservative
heuristics, not semantic alignment or verified classroom order.

The guide provider receives complete text from every page and supported speech
segment in a unit, rather than the learner's short preview. Provider output
cannot override source-derived teacher excerpts or assessment signals. Missing
example steps and practice roles remain missing; generic filler cannot upgrade
them to a complete lesson.

Strict checks also reject repeated example steps, known generic step filler,
reused questions across practice roles, tautological answers/explanations,
identical wrong/correct contrasts, and identical substantial explanations plus
bridges across distinct units. Comparisons retain math/code operators and case.
These rules catch observable failures; novel filler and incorrect but detailed
reasoning still require substantive evaluation and human review.

The repository now includes a local rendered-page adapter and an optional
`VisionProvider`/`OpenAIVisionProvider`. A review screen for accepting or
rejecting alignment and visual candidates, profile-specific signal rules,
SQLite search for larger courses, and MCP/Responses adapters over `StudyAgent`
remain next extensions.

## 材料整理与精讲

`LearningUnit.content_mode` 区分 `material-only` 和 `lesson`。未命中具体离线例题的单元保留完整原文，不再生成通用例题、答案和练习。只有解析出教学内容的模型回答才能切换为 `lesson`；这不意味着教学正确性已验证，质量门槛与草稿状态仍独立检查。

网页、Markdown 和 HTML 均明确显示材料整理状态，材料单元不能标记为学习完成，也不进入课后题。旧版 JSON 没有这个可选字段时按 `lesson` 加载，保留原有阅读内容；重新生成后使用新的材料视图。JSON Schema 保持向后兼容，严格讲义检查不接受 `material-only` 作为完整课程。
