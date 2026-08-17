"""Build a working parser from the frozen Lark artifact.

A grammar file nobody runs is prose. This module turns `rhoform.lark` into an
actual parser, which is what makes the conformance test in `lang/tests/` a
test of the grammar rather than a test of a string.

It deliberately knows nothing about the bake-off corpus: the anchoring — "the
frozen grammar accepts exactly what the winning prototype accepts" — lives in
the test, because the prototype is throwaway and this module is not. AMB-43
generates the real parser from the same artifact and can start here.

`lark` is a REQUIRED pin in toolchain/versions.yaml — required precisely
because a Lark artifact no parser has ever loaded proves nothing about the
grammar it claims to freeze. Absent, a caller gets `LarkUnavailable` with the
install line, and the gate exits 2 rather than 0: an unavailable gate is not
a pass.
"""

from pathlib import Path

GRAMMAR_PATH = Path(__file__).resolve().parent / "rhoform.lark"

# Lark's Indenter needs the terminal names its postlex step manufactures, plus
# the bracket terminals that suspend indentation. Implicit line joining inside
# `(` is what lets a long parameter list wrap, which is the one construct in
# the language that outgrows a line.
_INDENTER = dict(
    NL_type="_NEWLINE",
    OPEN_PAREN_types=["LPAR", "LSQB"],
    CLOSE_PAREN_types=["RPAR", "RSQB"],
    INDENT_type="_INDENT",
    DEDENT_type="_DEDENT",
    tab_len=4,
)


class LarkUnavailable(RuntimeError):
    """Raised when the pinned parser generator is not installed."""


def normalize(source: str) -> str:
    """The one normalization the layout pass owes the grammar.

    The grammar is defined over a token STREAM, and in that stream every
    statement ends with a newline token — the tokenizer synthesizes one at the
    end of the last line whether or not the file's final byte is a line break.
    Lark's lexer reads raw text instead, so without this a file missing its
    trailing newline is rejected for a reason about its last byte rather than
    its syntax, while the prototype accepts it.

    Doing it here rather than loosening the grammar keeps the rule honest:
    every statement really is newline-terminated, and this is a property of
    the reader, not of the language.
    """
    return source if source.endswith("\n") else source + "\n"


def load_parser(**kwargs):
    """An LALR parser over the frozen grammar.

    LALR with Lark's contextual lexer, not Earley, and the choice is
    load-bearing rather than a performance preference: the contextual lexer
    only considers terminals the current parser state accepts, which is what
    keeps a closed-vocabulary word like the pin role `input` usable as an
    ordinary instance name. A context-free grammar with a global keyword set
    would reject `input = new ...`, which the prototype accepts.
    """
    try:
        from lark import Lark
        from lark.indenter import Indenter
    except ImportError as exc:  # pragma: no cover - exercised by absence
        raise LarkUnavailable(
            "lark is not installed, so the frozen grammar cannot be loaded or "
            "run. Install the pin from toolchain/versions.yaml: "
            "python3 -m pip install lark==1.3.0"
        ) from exc

    indenter = type("RhoformIndenter", (Indenter,), _INDENTER)
    return Lark(
        GRAMMAR_PATH.read_text(encoding="utf-8"),
        parser="lalr",
        postlex=indenter(),
        start="start",
        **kwargs,
    )


def main(argv: list[str] | None = None) -> int:
    """Gate: the frozen grammar parses everything the prototype renders.

    Exit codes follow tests/structure/check-layout.sh — 0 pass, 1 violation,
    2 when the gate could not run. An unavailable gate is not a pass, so a
    missing `lark` is a 2 and not a cheerful 0.

    The bake-off import is deliberately inside this function. The corpus is
    the anchor for the freeze and retires with the prototypes; the module
    itself stays free of it so that `load_parser` outlives `lang/bakeoff/`.
    """
    try:
        parser = load_parser()
    except LarkUnavailable as exc:
        print(f"grammar: UNAVAILABLE: {exc}")
        return 2

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bakeoff.arms import candidate_b
    from bakeoff.arms.base import VARIANTS
    from bakeoff.model import load_corpus

    problems: list[str] = []
    checked = 0
    for design_id, model in sorted(load_corpus().items()):
        for variant in VARIANTS:
            source = candidate_b.render(model, variant)
            checked += 1
            try:
                parser.parse(normalize(source))
            except Exception as exc:  # noqa: BLE001 - any parse failure is a fail
                problems.append(f"{design_id}/{variant}: {type(exc).__name__}: {exc}")

    for problem in problems:
        print(f"grammar: FAIL: {problem}")
    if problems:
        return 1
    print(
        f"grammar: PASS: the frozen grammar parses {checked} rendering(s) of "
        f"the bake-off corpus"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
