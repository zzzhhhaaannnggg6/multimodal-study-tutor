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
        "通用课程",
        "claim -> context/conditions -> evidence -> mechanism -> consequence",
        ("concept", "process", "argument", "example"),
        ("retrieval", "comparison", "transfer"),
    ),
    "computer-systems": StudyProfile(
        "computer-systems",
        "计算机系统",
        "machine state -> operation -> destination -> next state/PC",
        ("register", "ALU", "memory", "PC", "signal", "bit width"),
        ("trace", "bit-level calculation", "datapath comparison"),
    ),
    "mathematics": StudyProfile(
        "mathematics",
        "数学",
        "conditions/definitions -> representation/formula -> operations -> result -> check",
        ("definition", "domain", "formula", "proof", "counterexample", "units"),
        ("retrieval", "derivation", "worked calculation", "transfer"),
    ),
    "physics": StudyProfile(
        "physics",
        "物理",
        "quantities/units -> model/law -> substitution/derivation -> result -> limits",
        ("quantity", "unit", "law", "model", "measurement", "uncertainty"),
        ("retrieval", "derivation", "unit check", "estimate", "transfer"),
    ),
    "history": StudyProfile(
        "history",
        "历史与社会科学",
        "question/context -> claim -> source/evidence -> causal relation -> consequence/limit",
        ("period", "actor", "source", "claim", "cause", "consequence"),
        ("chronology", "evidence comparison", "causal explanation", "counterclaim"),
    ),
    "biology": StudyProfile(
        "biology",
        "生物",
        "structure -> function -> process/regulation -> evidence -> exception/application",
        ("structure", "function", "gene", "cell", "pathway", "evidence"),
        ("labeling", "process tracing", "evidence interpretation", "transfer"),
    ),
    "chemistry": StudyProfile(
        "chemistry",
        "化学",
        "species/conditions -> equation/model -> balancing/stoichiometry -> result -> limits",
        ("species", "mole", "concentration", "reaction", "equilibrium", "unit"),
        ("equation balancing", "stoichiometric calculation", "unit check", "prediction"),
    ),
    "law": StudyProfile(
        "law",
        "法学与专业规则",
        "rule/authority -> elements/conditions -> facts/application -> exception -> conclusion",
        ("rule", "authority", "element", "condition", "fact", "exception"),
        ("issue spotting", "rule application", "counterargument", "structured conclusion"),
    ),
    "literature": StudyProfile(
        "literature",
        "文学与文本解读",
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
