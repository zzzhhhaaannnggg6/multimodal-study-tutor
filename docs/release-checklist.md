# Release checklist

Before publishing a project or example:

- [ ] Run `python3 -m compileall -q src`.
- [ ] Run `python3 -m pytest -q` when pytest is installed.
- [ ] Run `study validate ... --strict` on every public lesson map.
- [ ] Confirm all `E3`/`E-` claims have a quote and a navigable locator.
- [ ] Search tracked text for `/Users/`, `/home/`, Windows user paths, API
      keys, teacher names, private transcript text, and unlicensed media.
- [ ] Confirm raw PPT, DOCX, audio, screenshots and generated private outputs
      are ignored by Git.
- [ ] Check that README commands work in a fresh virtual environment.
- [ ] Tag the release only after the example can run without network access.
