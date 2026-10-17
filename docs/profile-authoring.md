# Authoring a Subject Profile

A subject profile teaches the generic reconstruction engine how to organize a
discipline. It is configuration and domain vocabulary, not a second copy of
the pipeline. Keep reusable behavior in the core engine and put subject
judgment here.

## What a profile controls

A profile may define:

- display name, version, and supported languages;
- canonical terms, aliases, symbols, and unit conventions;
- knowledge-unit kinds, such as concept, process, proof, interpretation, or
  worked example;
- prerequisite and dependency hints;
- understanding levels (`U0` through `U3`) and evaluation signals (`E-`,
  `E0` through `E3`);
- discipline-specific evidence rules and high-risk claims;
- common misconceptions and contrast pairs;
- review-item templates and acceptable answer forms; and
- render labels used by Markdown, JSON, and the web view.

Do not use a profile to assert that a topic is definitely on an exam. An
evaluation signal records evidence observed in the supplied material or
transcript; uncertainty must remain visible.

## Recommended shape

Store profiles as versioned data under the profile directory used by the
project. The exact loader may evolve, but new profiles should provide these
logical sections:

```yaml
id: generic
version: 1
name: Generic study profile
language: zh-CN
terms:
  - canonical: example term
    aliases: [alternate term]
knowledge_unit_kinds: [concept, process, example, practice]
priority_levels:
  understanding: [U0, U1, U2, U3]
  evaluation: [E-, E0, E1, E2, E3]
evidence_rules:
  - claim_type: exam_signal
    requires: [teacher_statement, assessment_material]
misconceptions: []
review_templates: []
```

The loader should reject an unknown priority level, duplicate canonical term,
missing profile identifier, or evidence rule with no recognized source type.
Keep the schema strict enough to catch typos, while allowing optional fields
for a profile that does not need every review template.

## Evidence and provenance

Every generated claim should carry a provenance label and, when available, a
source locator. Use the following distinctions consistently:

- `material`: directly visible in a slide, page, figure, or supplied text;
- `teacher`: stated or clearly paraphrased in the supplied lecture channel;
- `bridge`: an explanatory connection added to make the relationship
  understandable;
- `synthesis`: a conclusion supported by multiple cited sources; and
- `uncertain`: ambiguous, conflicting, or incomplete evidence.

Profiles may raise the evidence requirement for risky claims such as numerical
values, formulas, legal rules, historical dates, safety instructions, or
assertions about assessment. They must not lower the global requirement that a
claim be traceable or marked uncertain.

## Authoring workflow

1. Start with a small vocabulary and three or four knowledge-unit kinds.
2. Add one representative lesson fixture and map each claim to a page,
   timestamp, or other stable locator.
3. Encode only distinctions that change reconstruction or review behavior.
4. Add misconception and review templates after the basic lesson passes
   validation.
5. Run schema, provenance, and golden-output tests before changing the
   profile version.
6. Document any terms whose meaning differs across textbooks or regions.

Prefer stable identifiers over display text. A renamed label should not break
old project files; a changed meaning should increment the profile version and
include a migration note.

## Quality checks

A profile is ready for review when:

- a minimal fixture can be ingested without profile-specific code paths;
- every high-priority claim has an evidence rule and source locator;
- bridge explanations are visibly distinct from teacher statements;
- conflicting sources produce an uncertainty marker rather than silent choice;
- review items test retrieval or transfer, not only copied wording; and
- the same profile can render both an understanding view and a concise review
  view.

Never include real learner records, private recordings, or unlicensed course
materials in a profile pull request. Use synthetic fixtures or materials whose
redistribution permission is documented.
