# Release checklist

Before publishing a project or example:

- [ ] Run `python3 -m compileall -q src`.
- [ ] Run `python3 -m pytest -q` when pytest is installed.
- [ ] Run `study validate ... --strict` on every public lesson map.
- [ ] Run `study validate-guide ... --strict` on every public student guide.
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
- [ ] Search tracked text for `/Users/`, `/home/`, Windows user paths, API
      keys, teacher names, private transcript text, and unlicensed media.
- [ ] Confirm raw PPT, DOCX, audio, screenshots and generated private outputs
      are ignored by Git.
- [ ] Check that README commands work in a fresh virtual environment.
- [ ] Tag the release only after the example can run without network access.
