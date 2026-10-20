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
   scaffold. `mst.guide` then turns a map into a student-facing learning
   guide, while keeping all page/time references attached.
4. **Surfaces** — the CLI, local study route, Markdown/HTML exports, and Agent
   API consume the map or guide. The map stays evidence-first; the guide is
   readable without understanding internal IDs or U/E levels.

## Data flow

```text
source files -> project.json -> lesson-map.json -> study-guide.json -> Markdown/Web/Agent
                    |                |
                 hashes          validation
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

## Current boundaries and next extensions

The deterministic signal layer can detect structure in extracted text and PPTX
shape XML, but it does not claim to read a screenshot, recognize an equation
from pixels, or hear an audio file without a speech provider. Pages with images,
formulas or connectors receive a visible visual-review flag; transcript
segments without lexical anchors remain classroom supplements or unresolved.

Next extensions are a rendered-page/vision adapter, a review screen for
accepting or rejecting alignment candidates, profile-specific signal rules,
SQLite search for larger courses, and MCP/Responses adapters over
`StudyAgent` tools.
