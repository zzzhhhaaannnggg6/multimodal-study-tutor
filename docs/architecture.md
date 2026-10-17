# Architecture

The repository is intentionally split into four layers:

1. **Core contract** — `mst.models` describes portable source, alignment,
   knowledge, evidence and review records. `mst.validation` rejects claims that
   cannot be traced back to a source.
2. **Preparation** — `mst.ingest` records source metadata and hashes without
   editing original files. Parsers for PPT/PDF/audio/transcript can be added
   behind this boundary.
3. **Reconstruction** — `mst.reconstruct` currently creates a deterministic
   provenance scaffold. Model providers and subject profiles enrich the same
   map rather than inventing a parallel output format.
4. **Surfaces** — the CLI, local timeline, and Agent API consume the map. This
   keeps the evidence contract identical in terminal, browser, and chat.

## Data flow

```text
source files -> project.json -> lesson-map.json -> Markdown/Web/Agent
                    |                |
                 hashes          validation
```

The map is an interchange artifact. It is safe to regenerate derived files,
while source assets remain outside the public repository by default.

## Provider boundary

`ModelProvider.complete(system, user, response_format)` is the only model
surface required by the first release. `MockProvider` makes CI deterministic;
`OpenAIProvider` is optional and lazy-loaded. A future local model or another
host can implement the same protocol without changing the map schema.

## Planned extensions

- format-specific parsers that emit `VisualFrame` and `SpeechSegment`;
- alignment review UI with explicit jump-page and unresolved states;
- profile registry for domain-specific terminology and practice strategies;
- SQLite search index for larger courses;
- MCP/Responses adapters over `StudyAgent` tools.
