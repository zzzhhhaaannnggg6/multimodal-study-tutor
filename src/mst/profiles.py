"""Subject-profile registry used by CLI and integrations."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StudyProfile:
    profile_id: str
    label: str
    trace_template: str
    terminology: tuple[str, ...] = field(default_factory=tuple)
    practice_modes: tuple[str, ...] = field(default_factory=tuple)


PROFILES: dict[str, StudyProfile] = {
    "generic": StudyProfile(
        "generic",
        "Cross-subject",
        "claim -> context/conditions -> evidence -> mechanism -> consequence",
        ("concept", "process", "argument", "example"),
        ("retrieval", "comparison", "transfer"),
    ),
    "computer-systems": StudyProfile(
        "computer-systems",
        "Computer systems",
        "machine state -> operation -> destination -> next state/PC",
        ("register", "ALU", "memory", "PC", "signal", "bit width"),
        ("trace", "bit-level calculation", "datapath comparison"),
    ),
    "mathematics": StudyProfile(
        "mathematics",
        "Mathematics",
        "conditions/definitions -> representation/formula -> operations -> result -> check",
        ("definition", "domain", "formula", "proof", "counterexample", "units"),
        ("retrieval", "derivation", "worked calculation", "transfer"),
    ),
    "physics": StudyProfile(
        "physics",
        "Physics",
        "quantities/units -> model/law -> substitution/derivation -> result -> limits",
        ("quantity", "unit", "law", "model", "measurement", "uncertainty"),
        ("retrieval", "derivation", "unit check", "estimate", "transfer"),
    ),
    "history": StudyProfile(
        "history",
        "History and social sciences",
        "question/context -> claim -> source/evidence -> causal relation -> consequence/limit",
        ("period", "actor", "source", "claim", "cause", "consequence"),
        ("chronology", "evidence comparison", "causal explanation", "counterclaim"),
    ),
    "biology": StudyProfile(
        "biology",
        "Biology",
        "structure -> function -> process/regulation -> evidence -> exception/application",
        ("structure", "function", "gene", "cell", "pathway", "evidence"),
        ("labeling", "process tracing", "evidence interpretation", "transfer"),
    ),
    "chemistry": StudyProfile(
        "chemistry",
        "Chemistry",
        "species/conditions -> equation/model -> balancing/stoichiometry -> result -> limits",
        ("species", "mole", "concentration", "reaction", "equilibrium", "unit"),
        ("equation balancing", "stoichiometric calculation", "unit check", "prediction"),
    ),
    "law": StudyProfile(
        "law",
        "Law and professional rules",
        "rule/authority -> elements/conditions -> facts/application -> exception -> conclusion",
        ("rule", "authority", "element", "condition", "fact", "exception"),
        ("issue spotting", "rule application", "counterargument", "structured conclusion"),
    ),
    "literature": StudyProfile(
        "literature",
        "Literature and text interpretation",
        "question/context -> passage/form -> interpretation -> alternative reading -> supported claim",
        ("passage", "narrator", "form", "image", "theme", "interpretation"),
        ("close reading", "evidence comparison", "interpretation", "counter-reading"),
    ),
}


def get_profile(profile_id: str) -> StudyProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {profile_id!r}; choose one of: {choices}") from exc


def list_profiles() -> list[StudyProfile]:
    return [PROFILES[key] for key in sorted(PROFILES)]
