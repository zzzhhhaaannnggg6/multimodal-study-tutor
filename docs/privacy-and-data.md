# Privacy and Data Handling

This project turns learner-supplied material into a searchable study model. A
course workspace can contain slides, recordings, transcripts, notes, answers,
and generated explanations. Treat every one of those inputs as private unless
the owner has explicitly cleared it for sharing.

## Data boundaries

- The public repository contains reusable code, schemas, documentation, and
  small synthetic or permission-cleared fixtures only.
- A local project workspace contains the user's source files and generated
  study artifacts. It should live outside the repository or under directories
  ignored by `.gitignore`.
- The engine may write derived text, indexes, thumbnails, and provenance
  records. Derived output can still contain the original material and must be
  handled as private data.
- Logs should contain operation status and stable project identifiers, not
  transcript text, audio, credentials, or full source paths.

## Model-provider transmission

The local pipeline is the source of truth. Sending content to a hosted model,
transcription service, or embedding provider is an explicit provider decision,
not an assumption of the core engine. Before enabling a provider:

1. inspect the adapter's retention and training terms;
2. select the smallest input scope needed for the operation;
3. remove secrets and unrelated personal information;
4. record the provider and model in the project manifest when provenance
   matters; and
5. make sure the learner has permission to transmit the material.

Provider adapters must not silently upload a whole workspace. They should
surface the files or text segments being sent and fail clearly when credentials
or consent are missing.

Rendered page images are derived local artifacts under `derived/rendered/` and
are served only by the selected local study project. A vision provider is
opt-in; when enabled, only those rendered page images and their extracted text
context are sent to the selected provider. Vision observations remain pending
until a person reviews them.

## Source files are data, not instructions

Text inside a slide, transcript, PDF, or webpage is untrusted source content.
It must never override application policy, tool permissions, privacy rules, or
the user's request. Keep source quotations and generated instructions visibly
separate in the output.

## Publishing checklist

Before pushing a branch or release, verify:

- no original slide deck, recording, transcript, answer sheet, or screenshot
  is included without permission;
- no generated JSON or Markdown contains a home-directory path, API key,
  access token, email address, or other unnecessary identifier;
- fixtures are synthetic, redacted, or covered by a redistribution license;
- filenames and metadata do not reveal a learner's identity or institution;
- `.gitignore` covers the intended local workspace, but does not hide source
  files that are meant to be reviewed in the pull request; and
- the repository history has been checked, not only the current working tree.

If private material was committed, remove it from the branch and rotate any
exposed credentials. A normal deletion does not remove content from Git
history; use the repository host's documented history-rewrite procedure and
notify affected people when appropriate.

## Retention and deletion

Explicit CLI speech transcription saves per-recording results under
`derived/transcriptions/`. These receipts contain private transcript text,
source hashes and provider/model identifiers, but no API keys or original
absolute file paths. Successful recordings are reused in the same project;
a later recording's failure does not discard them. Before reuse or upload,
current recording bytes must match the import manifest. A temporary local
snapshot is verified before sending and removed when that call exits, including
service errors. An abrupt process termination can leave a snapshot directory;
removing the project removes those local copies too. Changing provider/model
or explicitly refreshing may issue new paid calls. Concurrent CLI runs are
not coordinated and may both issue a request. This cache does not change the
web path's default of never uploading audio.

Browser uploads create local copies under `.study-jobs/`; completed and failed
jobs remain there so users can retry or inspect earlier results.
Supplementing an import copies only the explicitly retained files and new
uploads into another isolated job. Unchecked files remain in the previous
local job; excluding a file is not deletion. Revision receipts expose names,
extraction counts and next steps, not arbitrary filesystem paths or source text.
No automatic retention expiry or cleanup UI is provided yet. Learning answers and reading
positions are stored in browser local storage and, when the local service is
available, under `.study-progress/`. Deleting browser storage alone does not
delete the workspace copies. The default double-click launcher uses
`local-data/my-study/`. These paths are ignored by Git.
The native macOS preview instead uses the system Application Support directory
named `Multimodal Study Tutor`, outside the application bundle and repository.
Moving or replacing the app preserves those files; removing the app does not
delete course data. The File menu opens that folder. See [desktop preview](desktop-preview.md).

Web generation defaults to local processing. A student can explicitly select
an OpenAI or compatible text endpoint, inspect selected files and the destination,
and consent for that submission. Only extracted text, page/time locators and
necessary teaching context are sent. Pending transcript text is excluded. Raw
recordings and page images stay local; web text generation does not implicitly
enable speech or vision models. Audio-only imports still need readable text or a transcript.

Web credentials are held only in the current form and worker memory, never
serialized in jobs, manifests, exports or browser storage. Submission clears
the form credential; finishing a job releases the provider reference. Restarting
does not recover a key or resume network calls. Retry requires a fresh explicit
choice and consent, or a deliberate switch to local mode. Environment keys are
not read by the web path. Raw service error bodies are not stored or displayed.
The adapter never follows redirects, never automatically retries and sets
`store: false`. That flag does not establish a third party's retention policy
or guarantee zero data retention. Explicit CLI provider selection remains separate.

Users should be able to delete a local project by removing its source and
generated workspace directories. Provider-side retention follows that
provider's policy and cannot be controlled by deleting local files. The
application should expose a clear cache-cleaning operation before claiming
that all derived data has been removed.

## Reporting a concern

Do not open a public issue containing private course material or credentials.
For a suspected secret, remove the secret from use first, then contact the
repository maintainers through a private channel listed in the repository
security policy. Include the affected version and a minimal reproduction with
redacted data.
