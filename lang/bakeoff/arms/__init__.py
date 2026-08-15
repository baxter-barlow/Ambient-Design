"""The arm registry: the three things §8-Q1 and §4 put side by side.

Two L5-conformant candidates and the Starlark-restricted-Python baseline.
Everything downstream — the measurement, the gates, the defect corpus, the
CLI — iterates this registry, so adding a fourth arm is one entry here and
nothing else, and no measurement can quietly cover only some of them.
"""

from dataclasses import dataclass

from . import candidate_a, candidate_b, starlark


@dataclass(frozen=True)
class Arm:
    key: str
    title: str
    code_prefix: str
    variants: tuple[str, ...]
    kind: str
    module: object

    def render(self, model, variant: str = "explicit") -> str:
        return self.module.render(model, variant)

    def parse(self, source: str, variant: str = "explicit"):
        return self.module.parse(source, variant)

    def language_card(self) -> str:
        return self.module.language_card()

    def source_filename(self, design_id: str) -> str:
        suffix = "py" if self.kind == "baseline" else "aed"
        return f"{design_id}.{suffix}"


ARMS: dict[str, Arm] = {
    "candidate_a": Arm(
        key="candidate_a",
        title=candidate_a.TITLE,
        code_prefix=candidate_a.CODE_PREFIX,
        variants=("explicit", "inferred", "inferred+columnar"),
        kind="candidate",
        module=candidate_a,
    ),
    "candidate_b": Arm(
        key="candidate_b",
        title=candidate_b.TITLE,
        code_prefix=candidate_b.CODE_PREFIX,
        variants=("explicit", "inferred", "inferred+columnar"),
        kind="candidate",
        module=candidate_b,
    ),
    "starlark": Arm(
        key="starlark",
        title=starlark.TITLE,
        code_prefix=starlark.CODE_PREFIX,
        # No columnar cell: Python has no columnar sub-syntax, and inventing
        # one so the table would have no gaps in it would be reporting a
        # number for a construct nobody proposed.
        variants=("explicit", "inferred"),
        kind="baseline",
        module=starlark,
    ),
}

CANDIDATES = tuple(arm for arm in ARMS.values() if arm.kind == "candidate")


def arm(key: str) -> Arm:
    try:
        return ARMS[key]
    except KeyError:
        raise KeyError(
            f"unknown arm {key!r}; the bake-off runs " + ", ".join(sorted(ARMS))
        ) from None
