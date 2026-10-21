# Release checklist

Before publishing a project or example:

- [ ] Run `python3 -m compileall -q src`.
- [ ] Run `python3 -m pytest -q` when pytest is installed.
- [ ] Run `study validate ... --strict` on every public lesson map.
- [ ] Run `study validate-guide ... --strict` on every public student guide.
- [ ] Run `study evaluate evals/number-conversion-v1.json`; inspect failed cases
      and retain the report. Treat a pass as bounded numerical evidence, not
      as expert review or student independent-learning acceptance.
- [ ] Confirm every core guide unit has a complete worked example with at
      least three steps, a one-condition variation, an error contrast, three
      practice roles (retrieval/process/transfer), and a navigable source
      reference; drafts are labelled as drafts.
- [ ] Run a blind student check: without opening the original materials, a
      learner can state the lesson route, solve the worked example, complete a
      transfer item, and find the source for each central conclusion.
- [ ] Check Markdown and standalone HTML keep answers collapsed until the
      learner asks to reveal them.
- [ ] Confirm all `E3`/`E-` claims have a quote and a navigable locator.
- [ ] Inspect pages marked as requiring visual review; confirm diagrams, formulas,
      screenshots and code blocks are either reviewed or visibly left pending.
- [ ] Inspect speech-role counts and alignment candidates; reject weak page
      matches and keep genuine classroom supplements separate.
- [ ] Try a transcript from a different lesson: it must remain pending when
      source support is insufficient, and must not enter the guide's teacher
      explanation. Check that timestamp-only paragraphs do not become quotes.
- [ ] Reject short model answers rather than padding example steps or missing
      practice roles. Keep assessment signals tied to the evidence layer.
- [ ] Check plain, single-headed and double-headed connections separately;
      inspect rotated/grouped arrows and explicit super/subscripts.
- [ ] Search tracked text for `/Users/`, `/home/`, Windows user paths, API
      keys, teacher names, private transcript text, and unlicensed media.
- [ ] Confirm raw PPT, DOCX, audio, screenshots and generated private outputs
      are ignored by Git.
- [ ] Check that README commands work in a fresh virtual environment.
- [ ] Build and install a wheel outside the checkout; fetch HTML, JavaScript and CSS.
- [ ] Run `npm test` and `npm run test:web` for desktop and mobile workflows.
- [ ] Verify corrupt input, concurrent submission and service shutdown preserve the old course.
- [ ] Verify per-file receipts distinguish unreadable/partial/audio-only input; supplement saved sources and replace one file without overwriting the prior job.
- [ ] Verify model uploads require per-submission consent, exclude unchecked and pending sources, never persist keys, stop after service errors and never follow redirects.
- [ ] Verify model planning success alone, empty prose or invalid teaching content cannot replace a saved course; distinguish simulated API checks from live-provider acceptance.
- [ ] Verify reading and answer drafts restore without browser storage, and changed units invalidate stale progress.
- [ ] Verify the macOS launcher opens existing work without generating it again.
- [ ] Tag the release only after the example can run without network access.
