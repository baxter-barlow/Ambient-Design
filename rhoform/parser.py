"""The production parser (R12/L5): the frozen grammar, error-tolerant.

WHAT "GENERATED FROM THE SOURCE OF TRUTH" MEANS HERE. This module contains
no grammar. It loads `lang/grammar/rhoform.lark` — the artifact rendered
from `rhoform_syntax.py` and held to it by `make grammar` — and builds
Lark's LALR parser with the contextual lexer and an INDENT/DEDENT postlex,
the same construction `lang/grammar/conformance.py` proved out. The closed
vocabularies are read from the same source-of-truth module (they are
published there as CLOSED_VOCABULARIES precisely so tools can consume
them), and the L8 pragma text is recovered from the artifact's own PRAGMA
terminal. If the grammar changes, this parser changes with it, because it
carries nothing that could fall behind.

ERROR TOLERANCE, BY RESTART. A parse never stops at the first defect (P2:
one problem per repair round is the convergence failure the language exists
to avoid). Recovery is restart-based: report the error, BLANK the offending
text — the single character for a lexical error, the physical line for a
parse error — and parse again from the top, up to _RECOVERY_LIMIT
diagnostics. Blanking replaces bytes with spaces, so every offset in every
later diagnostic still names the author's own bytes; a blank line carries
no layout, so INDENT/DEDENT structure degrades predictably; and the final
tree is exactly "the file with its broken statements removed", which is
the honest best effort. The alternative — token-level resynchronization
inside the LALR automaton — was tried first and produced a diagnostic per
token whenever the parser was stuck in a state no statement boundary could
satisfy; restart parsing is quadratic in the worst case and correct, and
the recovery limit bounds the constant.

Four shapes get special handling so one defect is one diagnostic:

  - The L8 pragma. A missing or wrong header is ONE RHO1005 with a
    machine-applicable fix-it; the parse then runs over the source with a
    correct header prepended (and the wrong one blanked), and every
    reported offset is translated back so spans never name synthetic
    text. A pragma appearing MID-line is the frozen v0.1 decision,
    reported once as RHO1013, not per character.
  - A blanked statement's block. Blanking a parse-error line also blanks
    its subordinate block, unconditionally: the defect was the statement,
    and its body deserves silence, not one error per line. (A reactive
    rule that waited for the block's INDENT to be rejected missed the
    case where the broken statement led its block — the Indenter simply
    established the level one deeper; review round 1.)
  - A quantity in the wrong FORM. ` +/- 1%` after a plain quantity lexes
    as nothing, so the generic path would charge one diagnostic per
    operator character; RHO1012 names the whole literal once instead.
  - An unterminated string blanks to end of line, not by the quote
    alone, so its words are not re-parsed as junk names.

Stage order: (1) a byte pre-scan reports every tab, carriage return,
control character, and non-ASCII byte with byte spans
(RHO1001/1003/1014/1002) and, when any fire, skips the grammar parse —
those defects are pre-syntactic, and diagnosing the structure of text
the author did not legally write would blame lines for bytes; (2) the
pragma pre-check; (3) the restart parse;
(4) post-parse file-local checks the prototype also made at parse level:
closed-vocabulary words (RHO1009) and quantity-literal semantics (RHO1010,
via rhoform.quantities). The table-row arity check is deliberately NOT
here — the grammar's own docstring assigns it to the checker.

Every diagnostic goes through rhoform.diagnostics; there is no second
reporting path.
"""

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path

from .diagnostics import Diagnostics, Edit, FixIt, Span, span_from_bytes
from .quantities import QuantityError, parse_quantity

_ROOT = Path(__file__).resolve().parents[1]
GRAMMAR_PATH = _ROOT / "lang" / "grammar" / "rhoform.lark"
_SOT_PATH = _ROOT / "lang" / "grammar" / "rhoform_syntax.py"

# The Indenter configuration, matching lang/grammar/conformance.py (a test
# in lang/tests anchors the two while both exist). Implicit line joining
# inside brackets is what lets a parameter list wrap.
_INDENTER = dict(
    NL_type="_NEWLINE",
    OPEN_PAREN_types=["LPAR", "LSQB"],
    CLOSE_PAREN_types=["RPAR", "RSQB"],
    INDENT_type="_INDENT",
    DEDENT_type="_DEDENT",
    tab_len=4,
)

# After this many parse-recovery diagnostics the tree is abandoned. A bound
# this small never triggers on a file a model plausibly wrote (the bake-off
# defect corpus peaks at 3 diagnostics per file); what it stops is a
# pathological input turning restart recovery into quadratic noise.
_RECOVERY_LIMIT = 20

# Which child of which rule carries a closed-vocabulary word, counted among
# the rule's DIRECT NAME-typed tokens (FREE_NAME is a distinct token type,
# and designators/arguments sit under their own subtrees, so the count is
# stable). Pinned by rhoform/tests against the generated grammar.
_VOCAB_SITES = {
    "port_decl": ("pin_role", 0),
    "pin_decl": ("pin_role", 1),
    "hardware_decl": ("hardware_kind", 0),
    "net_attribute": ("net_attribute", 0),
    "assertion": ("measurement_kind", 1),
}

_QUANTITY_TOKEN_TYPES = frozenset(
    {"QUANTITY", "QUANTITY_INTERVAL", "QUANTITY_PLAIN"}
)

_KEYWORD_PATTERN = re.compile(r"^(\w+)\(\?\!\[A\-Za\-z0\-9_\]\)$")

# Structural terminals rendered for humans. Keyword terminals are derived
# from the artifact's own patterns at load time; only the names below carry
# no keyword to derive a spelling from.
_TERMINAL_PROSE = {
    "FREE_NAME": "a name (not a keyword)",
    "NAME": "a name",
    "QUANTITY": "a quantity",
    "QUANTITY_INTERVAL": "a quantity interval",
    "QUANTITY_PLAIN": "a quantity",
    "NUMBER": "a number",
    "INTEGER": "an integer",
    "STRING": "a string",
    "PRAGMA": "the syntax-version pragma",
    "_NEWLINE": "end of line",
    "_INDENT": "indentation",
    "_DEDENT": "end of block",
    "$END": "end of file",
    "COLON": "`:`",
    "COMMA": "`,`",
    "LPAR": "`(`",
    "RPAR": "`)`",
    "LSQB": "`[`",
    "RSQB": "`]`",
    "EQUAL": "`=`",
    "TILDE": "`~`",
    "DOT": "`.`",
}


class LarkUnavailable(RuntimeError):
    """The pinned parser generator is not installed. Gates exit 2 on this:
    an unavailable parser is not a parser that passed."""


def _load_sot():
    """The grammar source-of-truth module, imported by file path.

    `rhoform_syntax.py` publishes CLOSED_VOCABULARIES and PRAGMA_TEXT for
    exactly this kind of consumer. Importing it by path (rather than
    copying the four lists here) is what keeps this parser incapable of
    disagreeing with the grammar about a vocabulary.
    """
    spec = importlib.util.spec_from_file_location(
        "_rhoform_grammar_sot", _SOT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize(source: str) -> str:
    """The one normalization the grammar is owed: a final newline token.

    Identical to conformance.normalize, and a property of the reader
    rather than the language — every statement really is
    newline-terminated in the token stream."""
    return source if source.endswith("\n") else source + "\n"


@dataclass
class _Loaded:
    parser: object
    pragma_text: str
    keyword_of: dict
    vocabularies: dict
    quantity_re: object  # the SoT's full five-form literal pattern


_CACHE: _Loaded | None = None


def _load() -> _Loaded:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        from lark import Lark
        from lark.indenter import Indenter
    except ImportError as exc:  # pragma: no cover - exercised by absence
        raise LarkUnavailable(
            "lark is not installed, so the frozen grammar cannot be loaded "
            "or run. Install the pin from toolchain/versions.yaml: "
            "python3 -m pip install lark==1.3.0"
        ) from exc

    indenter = type("RhoformIndenter", (Indenter,), _INDENTER)
    parser = Lark(
        GRAMMAR_PATH.read_text(encoding="utf-8"),
        parser="lalr",
        postlex=indenter(),
        start="start",
        propagate_positions=True,
    )

    pragma_text = None
    keyword_of = {}
    for terminal in parser.terminals:
        pattern = terminal.pattern
        value = getattr(pattern, "value", "")
        if terminal.name == "PRAGMA":
            # The artifact stores re.escape(PRAGMA_TEXT); unescaping
            # recovers the exact header without a second copy of the text.
            pragma_text = re.sub(r"\\(.)", r"\1", value)
        elif pattern.type == "re":
            match = _KEYWORD_PATTERN.match(value)
            if match:
                keyword_of[terminal.name] = match.group(1)

    sot = _load_sot()
    if pragma_text != sot.PRAGMA_TEXT:  # pragma: no cover - artifact drift
        raise RuntimeError(
            "the PRAGMA terminal in rhoform.lark does not unescape to the "
            "source of truth's PRAGMA_TEXT; regenerate the artifacts"
        )
    _CACHE = _Loaded(
        parser=parser,
        pragma_text=pragma_text,
        keyword_of=keyword_of,
        vocabularies=dict(sot.CLOSED_VOCABULARIES),
        quantity_re=re.compile(sot.LEXER_QUANTITY),
    )
    return _CACHE


@dataclass
class ParseResult:
    """A best-effort tree plus everything the parse had to say.

    `tree` is None when recovery was abandoned (byte-level defects, or
    more than _RECOVERY_LIMIT parse errors); `diagnostics` is
    authoritative either way. When errors were recovered, `tree` describes
    the file with its broken lines blanked — stated here so no caller
    mistakes a recovered tree for the author's full intent. `ok` is the A2
    write-gate question: a complete tree and no error-severity
    diagnostics."""

    tree: object | None
    diagnostics: Diagnostics
    file: str

    @property
    def ok(self) -> bool:
        return self.tree is not None and not self.diagnostics.has_errors


def _describe_terminal(name: str, keyword_of: dict) -> str:
    if name in keyword_of:
        return f"`{keyword_of[name]}`"
    return _TERMINAL_PROSE.get(name, name)


def _describe_token(token, keyword_of: dict) -> str:
    kind = _describe_terminal(token.type, keyword_of)
    text = str(token)
    if token.type == "$END" or not text.strip():
        return kind
    if kind.startswith("`"):
        return kind
    excerpt = text if len(text) <= 30 else text[:27] + "..."
    return f"`{excerpt}` ({kind})"


def _expected_list(names, keyword_of: dict) -> str:
    described = sorted(
        {_describe_terminal(name, keyword_of) for name in names}
    )
    return ", ".join(described) if described else "nothing (internal state)"


def _prescan(file: str, data: bytes, sink: Diagnostics) -> bool:
    """Byte-level legality: tabs, CR, control chars, non-ASCII. True when
    clean. Offsets accumulate in BYTES over a surrogateescape decoding,
    because that round-trips every byte exactly: a decode with
    errors="replace" turned one invalid byte into a three-byte U+FFFD and
    every span after it drifted by two — a violation of the one promise
    byte spans make (found by the first independent review)."""
    clean = True
    text = data.decode("utf-8", errors="surrogateescape")
    # Walk BYTES for offsets, characters for codepoints: a multi-byte
    # UTF-8 character is one diagnostic at its first byte, not three.
    offset = 0
    for char in text:
        code = ord(char)
        escaped_byte = 0xDC80 <= code <= 0xDCFF  # surrogateescape's range
        width = 1 if escaped_byte else len(char.encode("utf-8"))
        if char == "\t":
            clean = False
            span = span_from_bytes(file, data, offset, offset + 1)
            sink.add(
                "RHO1001", {}, primary=span,
                fixits=(FixIt(
                    "replace the tab with spaces (the right count depends "
                    "on the intended block)",
                    "needs-review",
                    (Edit(span, "    "),),
                ),),
            )
        elif char == "\r":
            clean = False
            span = span_from_bytes(file, data, offset, offset + 1)
            sink.add(
                "RHO1003", {}, primary=span,
                fixits=(FixIt(
                    "remove the carriage return",
                    "machine-applicable",
                    (Edit(span, ""),),
                ),),
            )
        elif (code < 0x20 and char != "\n") or code == 0x7F:
            # ASCII control characters are not "non-ASCII": DEL reported
            # as U+007F under a non-ascii slug was factually wrong, so
            # they carry their own code (review round 1).
            clean = False
            span = span_from_bytes(file, data, offset, offset + 1)
            sink.add("RHO1014", {"codepoint": f"U+{code:04X}"},
                     primary=span)
        elif code > 0x7E:
            clean = False
            span = span_from_bytes(file, data, offset, offset + width)
            if escaped_byte:
                codepoint = f"0x{code - 0xDC00:02X} (not valid UTF-8)"
            else:
                codepoint = f"U+{code:04X}"
            replacement = {"±": "+/-", "µ": "u", "μ": "u",
                           "Ω": "ohm", "Ω": "ohm"}.get(char)
            fixits = ()
            if replacement is not None:
                fixits = (FixIt(
                    f"use the ASCII spelling `{replacement}`",
                    "machine-applicable",
                    (Edit(span, replacement),),
                ),)
            sink.add("RHO1002", {"codepoint": codepoint}, primary=span,
                     fixits=fixits)
        offset += width
    return clean


def _pragma_precheck(file: str, source: str, data: bytes, loaded: _Loaded,
                     sink: Diagnostics) -> tuple[str, int]:
    """Check the L8 header; return (text to parse, offset shift).

    The first content line — not blank, not a comment (a `#` line whose
    word is not `pragma`; `#pragmatic` is a comment, per the frozen
    boundary) — must be exactly the pragma. When it is, the source parses
    as-is and the shift is 0. When it is not, ONE RHO1005 is emitted with
    a machine-applicable fix-it, and the parse input becomes the correct
    header plus the source (with a wrong header line blanked), so the body
    is still checked; the returned shift translates every parse-input
    offset back onto the author's bytes.
    """
    expected = loaded.pragma_text
    offset = 0
    for line in source.split("\n"):
        stripped = line.strip()
        if stripped and not (
            stripped.startswith("#")
            and not re.match(r"#pragma(?![A-Za-z0-9_])", stripped)
        ):
            break
        offset += len(line) + 1
    else:
        line = None

    if line is not None and line.strip() == expected:
        return source, 0

    if line is not None and line.strip().startswith("#pragma"):
        start = offset + (len(line) - len(line.lstrip(" ")))
        end = min(offset + len(line), len(data))
        span = span_from_bytes(file, data, start, end)
        sink.add(
            "RHO1005",
            {"expected": expected, "found": f"`{line.strip()}`"},
            primary=span,
            fixits=(FixIt(
                f"replace the line with `{expected}`",
                "machine-applicable",
                (Edit(span, expected),),
            ),),
        )
        blanked = source[:offset] + " " * len(line) \
            + source[offset + len(line):]
        return expected + "\n" + blanked, len(expected) + 1

    insert_at = min(offset, len(data))
    span = span_from_bytes(file, data, insert_at, insert_at)
    if line is None:
        found = "end of file"
    else:
        text = line.strip()
        found = f"`{text if len(text) <= 40 else text[:37] + '...'}`"
    sink.add(
        "RHO1005",
        {"expected": expected, "found": found},
        primary=span,
        fixits=(FixIt(
            f"insert `{expected}` as the first line",
            "machine-applicable",
            (Edit(span, expected + "\n"),),
        ),),
    )
    return expected + "\n" + source, len(expected) + 1


def _line_bounds(text: str, offset: int) -> tuple[int, int]:
    """[start, end) of the physical line containing `offset`, sans newline."""
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return start, len(text) if end == -1 else end


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _indent_of(text: str, line_start: int) -> int:
    count = 0
    for char in text[line_start:]:
        if char != " ":
            break
        count += 1
    return count


def _blank_block(text: str, header_start: int, header_indent: int) -> str:
    """Blank every following line indented deeper than the header line.

    The orphaned-block rule: when a blanked statement introduced a block,
    the block's lines are the defect's shadow, not defects of their own.
    The header's indent is passed in because the header itself is already
    blanked — an all-space line would misreport its own depth. Blank and
    comment-only lines inside the run are blanked too (they belong to the
    block); the run ends at the first content line at or left of the
    header's indent."""
    _, header_end = _line_bounds(text, header_start)
    position = header_end + 1
    while position < len(text):
        start, end = _line_bounds(text, position)
        content = text[start:end].strip()
        if content and not content.startswith("#"):
            if _indent_of(text, start) <= header_indent:
                break
        text = _blank(text, start, end)
        position = end + 1
    return text


def _restart_parse(file: str, data: bytes, parse_text: str, shift: int,
                   loaded: _Loaded, sink: Diagnostics):
    """Parse, reporting and blanking one defect per round. Returns the
    final tree, or None when recovery was abandoned."""
    from lark.exceptions import UnexpectedCharacters, UnexpectedToken
    from lark.indenter import DedentError

    def span_at(pos: int, end: int) -> Span:
        start = max(0, min(pos - shift, len(data)))
        stop = max(start, min(end - shift, len(data)))
        if start == stop and start > 0 and start >= len(data):
            start -= 1
        return span_from_bytes(file, data, start, stop)

    # line start -> the line's indent BEFORE it was blanked; the emptied-
    # header rule needs the original depth, not a field of spaces' depth.
    # Normalized ONCE, up front, so every token position — including the
    # EOF-flushed DEDENTs that borrow from the synthesized final newline —
    # indexes into the text the loop actually edits. Normalizing only at
    # the parse call left a file without a final newline one byte out of
    # frame, and the emptied-header search then blamed the line above the
    # real defect (review round 2).
    parse_text = normalize(parse_text)
    blanked_lines: dict[int, int] = {}
    # Headers whose subordinate lines RECOVERY blanked. Only these may be
    # silenced when the parser later wants the block they no longer
    # introduce — an author's own genuinely empty block, with unrelated
    # errors elsewhere, must still be reported, so "we emptied it" is
    # tracked precisely rather than inferred from any-blanking-happened.
    suspect_headers: set[int] = set()
    baseline = len(sink)
    # Iterations, not diagnostics: silent blanking rounds (orphaned blocks,
    # emptied headers) consume iterations without emitting, and every round
    # blanks at least one character, so line-count-plus-limit terminates.
    budget = parse_text.count("\n") + _RECOVERY_LIMIT + 4
    for _ in range(budget):
        try:
            return loaded.parser.parse(parse_text)
        except UnexpectedCharacters as exc:
            pos = exc.pos_in_stream
            if pos >= len(parse_text):  # pragma: no cover - defensive
                return None
            char = parse_text[pos]
            line_start, line_end = _line_bounds(parse_text, pos)
            quantity_tail = _straddling_quantity(
                loaded, parse_text, line_start, line_end, pos)
            if char == '"':
                # The whole unterminated literal is the defect; blanking
                # only the quote would re-parse its words as junk names
                # and charge the author once per word.
                sink.add("RHO1004", {}, primary=span_at(pos, line_end))
                line_indent = _indent_of(parse_text, line_start)
                parse_text = _blank(parse_text, pos, line_end)
                if not parse_text[line_start:line_end].strip():
                    # The literal WAS the line: its enclosing block may
                    # now be empty, and that emptiness is recovery's.
                    parent = _parent_header(
                        parse_text, line_start, line_indent)
                    if parent is not None:
                        suspect_headers.add(parent)
            elif re.match(r"#pragma(?![A-Za-z0-9_])", parse_text[pos:]):
                # A `#pragma` the lexer refuses is mid-line (the header
                # pre-check settled line-initial ones): one diagnostic
                # for the frozen decision, not one per character of it.
                sink.add("RHO1013", {}, primary=span_at(pos, line_end))
                parse_text = _blank(parse_text, pos, line_end)
            elif quantity_tail is not None:
                # ` +/- 1%` after a plain quantity lexes as nothing, so
                # the generic path charged one diagnostic per character
                # of the operator. The defect is the literal's FORM in a
                # plain-quantity position; say that once, with the whole
                # literal in the span, and blank only the unconsumed tail.
                match_start, match_end, literal = quantity_tail
                sink.add("RHO1012", {"literal": literal},
                         primary=span_at(match_start, match_end))
                parse_text = _blank(parse_text, pos, match_end)
            elif (operator := _tolerance_operator(
                    loaded, parse_text, line_start, line_end, pos)
                  ) is not None:
                # A `+/-` after a quantity head that never became a full
                # literal — magnitude forgotten, spacing wrong, operator
                # doubled. One RHO1010 with a reason that matches the
                # actual shape, not one unexpected-character per operator
                # character (review rounds 2 and 3). The literal is
                # malformed, which is true in bound and value positions
                # alike.
                head, blank_end, literal, reason = operator
                sink.add(
                    "RHO1010",
                    {"literal": literal, "reason": reason},
                    primary=span_at(head, blank_end),
                )
                parse_text = _blank(parse_text, pos, blank_end)
            else:
                sink.add("RHO1011", {"character": f"`{char}`"},
                         primary=span_at(pos, pos + 1))
                content_start = line_start + _indent_of(parse_text,
                                                        line_start)
                if pos == content_start:
                    # Junk LEADING a line: no statement can open here,
                    # and blanking one character both manufactured
                    # indentation the author never wrote and left the
                    # residue to be blamed on innocent lines (review
                    # round 3, the third instance of the rounds-1/2
                    # genus). The line goes as a whole, with the same
                    # block and suspect-parent bookkeeping as a parse
                    # error.
                    line_indent = _indent_of(parse_text, line_start)
                    parent = _parent_header(parse_text, line_start,
                                            line_indent)
                    if parent is not None:
                        suspect_headers.add(parent)
                    blanked_lines[line_start] = line_indent
                    parse_text = _blank(parse_text, line_start, line_end)
                    parse_text = _blank_block(parse_text, line_start,
                                              line_indent)
                else:
                    parse_text = _blank(parse_text, pos, pos + 1)
        except UnexpectedToken as exc:
            token = exc.token
            expected_names = set(exc.accepts or exc.expected)
            expected = _expected_list(expected_names, loaded.keyword_of)
            # Layout tokens borrow their position from the newline run
            # that produced them, whose START sits at the end of the
            # PREVIOUS line; their END is the first content column of the
            # line they actually describe. Anchoring them at end_pos is
            # what keeps the orphaned-block rule pointed at the right line.
            if token.type == "$END":
                # $END borrows its position from the last real token,
                # which can itself be an EOF-flushed DEDENT carrying none;
                # end-of-text is what it means either way.
                pos = len(parse_text)
            elif token.type in ("_INDENT", "_DEDENT"):
                pos = token.end_pos if token.end_pos is not None else 0
            else:
                pos = token.start_pos if token.start_pos is not None else 0

            if "_INDENT" in expected_names:
                # The parser wants a block that is not there. Whatever
                # token arrived instead — the next module's keyword, a
                # DEDENT, end of file — the ARRIVING line is never the
                # defect; the empty-bodied header above it is. Blaming
                # the arrival blanked innocent statements (review round
                # 1's flood). So: find the header; if recovery itself
                # emptied it (a suspect), silence it — its emptiness is
                # our shadow; if the author wrote it empty, report ONE
                # diagnostic and blank the header, so everything after
                # it, including further defects, still gets parsed.
                header = _content_line_above(
                    parse_text, min(pos, len(parse_text)))
                if header is not None:
                    if header not in suspect_headers:
                        arrival = span_at(
                            min(pos, len(parse_text)),
                            min(token.end_pos
                                if token.end_pos is not None else pos + 1,
                                len(parse_text)),
                        )
                        if token.type == "$END":
                            sink.add("RHO1007", {"expected": expected},
                                     primary=arrival)
                        else:
                            sink.add(
                                "RHO1006",
                                {"found": _describe_token(
                                    token, loaded.keyword_of),
                                 "expected": expected},
                                primary=arrival,
                            )
                    indent = _indent_of(parse_text, header)
                    parent = _parent_header(parse_text, header, indent)
                    if parent is not None:
                        suspect_headers.add(parent)
                    blanked_lines[header] = indent
                    start, end = _line_bounds(parse_text, header)
                    parse_text = _blank(parse_text, start, end)
                    continue

            if token.type == "$END":
                if blanked_lines and _no_content_remains(parse_text):
                    # Recovery consumed every statement; this final
                    # failure is recovery's own artifact, and the
                    # diagnostics already tell the whole story.
                    return None
                end = len(parse_text)
                sink.add("RHO1007", {"expected": expected},
                         primary=span_at(end, end))
                return None

            pos = min(pos, len(parse_text) - 1)
            start, end = _line_bounds(parse_text, pos)
            sink.add(
                "RHO1006",
                {"found": _describe_token(token, loaded.keyword_of),
                 "expected": expected},
                primary=span_at(
                    pos,
                    token.end_pos if token.end_pos is not None else pos + 1,
                ),
            )
            indent = _indent_of(parse_text, start)
            parent = _parent_header(parse_text, start, indent)
            if parent is not None:
                suspect_headers.add(parent)
            blanked_lines[start] = indent
            parse_text = _blank(parse_text, start, end)
            # The blanked statement's subordinate block goes with it,
            # UNCONDITIONALLY: a reactive rule that waited for the block's
            # INDENT to be rejected missed the case where the broken
            # statement led its block — the Indenter then established the
            # enclosing level at the orphan's own depth and charged it one
            # diagnostic per line (review round 1). A statement's block
            # belongs to the statement; when the line had no block, this
            # blanks nothing.
            parse_text = _blank_block(parse_text, start, indent)
        except DedentError:
            # The Indenter raises without a position, so the offending
            # line is re-derived by walking the layout the way it does.
            # Swallowing this used to return no tree AND no diagnostics —
            # the one combination the framework must never produce.
            located = _first_bad_dedent(parse_text)
            if located is None:  # pragma: no cover - defensive
                return None
            start, end, indent = located
            # 1-based, like every other column in the wire format, and
            # the span opens exactly where the param points — at the
            # dedented CONTENT, not the indentation before it. A
            # diagnostic whose prose and span disagree by one is worse
            # than either convention alone.
            sink.add("RHO1008", {"column": indent + 1},
                     primary=span_at(start + indent, end))
            parent = _parent_header(parse_text, start, indent)
            if parent is not None:
                suspect_headers.add(parent)
            blanked_lines[start] = indent
            parse_text = _blank(parse_text, start, end)
            # Its block goes with it, same rule as a parse-error line:
            # round 2's review found the flood the round-1 fix removed
            # from the UnexpectedToken path alive and well on this one.
            parse_text = _blank_block(parse_text, start, indent)
        except Exception:  # pragma: no cover - lark internals
            return None
        if len(sink) - baseline >= _RECOVERY_LIMIT:
            return None
    return None  # pragma: no cover - budget exhausted without emitting


def _first_bad_dedent(text: str):
    """(line_start, line_end, column) of the first dedent matching no open
    level, mirroring the Indenter: blank and comment-only lines carry no
    layout, and lines inside brackets are not layout at all."""
    levels = [0]
    depth = 0
    position = 0
    while position < len(text):
        start, end = _line_bounds(text, position)
        line = text[start:end]
        stripped = line.strip()
        in_layout = depth == 0
        # Bracket depth for the NEXT line: count brackets outside strings
        # and comments on this one.
        in_string = False
        for char in line:
            if in_string:
                in_string = char != '"'
            elif char == '"':
                in_string = True
            elif char == "#":
                break
            elif char in "([":
                depth += 1
            elif char in ")]":
                depth = max(0, depth - 1)
        if in_layout and stripped and not stripped.startswith("#"):
            indent = _indent_of(text, start)
            if indent > levels[-1]:
                levels.append(indent)
            else:
                while indent < levels[-1]:
                    levels.pop()
                if indent != levels[-1]:
                    return start, end, indent
        position = end + 1
    return None


def _straddling_quantity(loaded: _Loaded, text: str, line_start: int,
                         line_end: int, pos: int):
    """(start, end, literal) of a full-form quantity literal on this line
    that CONTAINS the failing position strictly inside it, or None.

    This is how ` +/- 1%` after a plain quantity is recognized: the lexer
    consumed the plain head as its own token and then found no token at
    the operator, but the LINE, read with the SoT's full five-form
    pattern, shows one literal straddling the failure."""
    line = text[line_start:line_end]
    relative = pos - line_start
    for match in loaded.quantity_re.finditer(line):
        if match.start() < relative < match.end():
            return (line_start + match.start(), line_start + match.end(),
                    match.group(0))
    return None


_MAGNITUDE_RUN = re.compile(r"\s*-?[0-9.]*[A-Za-z0-9/%]*")


def _tolerance_operator(loaded: _Loaded, text: str, line_start: int,
                        line_end: int, pos: int):
    """(head_start, blank_end, literal, reason) for a `+/-` at `pos` whose
    literal never became a full form, or None.

    The complete-form-in-a-plain-position case is _straddling_quantity's;
    this covers everything the operator can do wrong: magnitude missing,
    spacing not exactly one on each side, operator doubled. The head must
    be a quantity on the same line with only spaces between it and the
    operator — a bare `+/-` with no head stays with the generic paths.
    The reason names the actual shape, because a stable structured param
    carrying a false sentence is worse than none (review round 3: the
    'no magnitude' reason on `100kohm +/-5%`, which has one)."""
    if text[pos:pos + 3] != "+/-":
        return None
    before = text[line_start:pos]
    for match in loaded.quantity_re.finditer(before):
        gap = before[match.end():]
        if gap != "" and gap.strip() == "":
            tail = _MAGNITUDE_RUN.match(text, pos + 3)
            blank_end = min(tail.end() if tail else pos + 3, line_end)
            after = text[pos + 3:blank_end]
            if not after.strip():
                reason = "the `+/-` operator has no magnitude after it"
            else:
                reason = ("a tolerance is spelled "
                          "`<value> +/- <magnitude>` with exactly one "
                          "space on each side of the operator")
            return (line_start + match.start(), blank_end,
                    text[line_start + match.start():blank_end], reason)
    return None


def _no_content_remains(text: str) -> bool:
    """True when nothing but blank lines, comments, and the pragma is left."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return False
    return True


def _nearest_line_above(text: str, line_start: int) -> int:
    """Start offset of the physical line directly above `line_start`."""
    if line_start == 0:
        return 0
    return text.rfind("\n", 0, line_start - 1) + 1


def _content_line_above(text: str, offset: int):
    """Start offset of the closest content line (not blank, not
    comment-only) STRICTLY above `offset`'s line, or None."""
    start = text.rfind("\n", 0, min(offset, len(text))) + 1
    while start > 0:
        start = _nearest_line_above(text, start)
        s, e = _line_bounds(text, start)
        content = text[s:e].strip()
        if content and not content.startswith("#"):
            return s
        if start == 0:
            return None
    return None


def _parent_header(text: str, line_start: int, indent: int):
    """The nearest content line above `line_start` with a SMALLER indent —
    the statement this line's block belongs to, or None at top level."""
    position = line_start
    while position > 0:
        position = _nearest_line_above(text, position)
        s, e = _line_bounds(text, position)
        content = text[s:e].strip()
        if content and not content.startswith("#") \
                and _indent_of(text, s) < indent:
            return s
        if position == 0:
            return None
    return None


def parse(source: str, file: str = "design.rhoform",
          sink: Diagnostics | None = None) -> ParseResult:
    """Parse one Rhoform source, tolerating errors. Never raises on bad
    input; raises LarkUnavailable only when the pinned lark is absent."""
    loaded = _load()
    sink = sink if sink is not None else Diagnostics()
    data = source.encode("utf-8", errors="surrogateescape")

    if not _prescan(file, data, sink):
        return ParseResult(tree=None, diagnostics=sink, file=file)

    parse_text, shift = _pragma_precheck(file, source, data, loaded, sink)
    tree = _restart_parse(file, data, parse_text, shift, loaded, sink)

    if tree is not None:
        _postparse(file, data, shift, tree, loaded, sink)
    return ParseResult(tree=tree, diagnostics=sink, file=file)


def _token_span(file: str, data: bytes, shift: int, token) -> Span:
    start = (token.start_pos or 0) - shift
    end = (token.end_pos if token.end_pos is not None else start) - shift
    start = max(0, min(start, len(data)))
    end = max(start, min(end, len(data)))
    return span_from_bytes(file, data, start, end)


def _postparse(file: str, data: bytes, shift: int, tree, loaded: _Loaded,
               sink: Diagnostics) -> None:
    """File-local checks past the grammar: vocabularies and quantities."""
    for node in tree.iter_subtrees():
        site = _VOCAB_SITES.get(node.data)
        if site is not None:
            vocabulary, index = site
            allowed = loaded.vocabularies[vocabulary]
            names = [child for child in node.children
                     if getattr(child, "type", None) == "NAME"]
            if index < len(names):
                word = names[index]
                if str(word) not in allowed:
                    span = _token_span(file, data, shift, word)
                    sink.add(
                        "RHO1009",
                        {"vocabulary": vocabulary, "word": str(word)},
                        primary=span,
                        fixits=_closest_fixit(str(word), allowed, span),
                    )
    for token in tree.scan_values(
        lambda value: getattr(value, "type", None) in _QUANTITY_TOKEN_TYPES
    ):
        try:
            parse_quantity(str(token))
        except QuantityError as exc:
            sink.add(
                "RHO1010",
                {"literal": str(token), "reason": exc.reason},
                primary=_token_span(file, data, shift, token),
            )


def _closest_fixit(word: str, allowed: tuple, span: Span) -> tuple:
    """A did-you-mean fix-it when one vocabulary entry is clearly closest."""
    from difflib import get_close_matches

    matches = get_close_matches(word, allowed, n=2, cutoff=0.6)
    if len(matches) != 1:
        return ()
    return (FixIt(
        f"did you mean `{matches[0]}`?",
        "needs-review",
        (Edit(span, matches[0]),),
    ),)


def main(argv: list[str] | None = None) -> int:
    """`python3 -m rhoform.parser <file>`: parse, emit NDJSON, exit like a
    gate — 0 clean, 1 error diagnostics, 2 parser unavailable. This is the
    module the conformance drivers and (later) the R18 CLI call."""
    import sys

    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python3 -m rhoform.parser <file.rhoform>",
              file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        # surrogateescape, not strict: a file with an invalid byte is a
        # DIAGNOSABLE input — RHO1002 with the exact byte span — and a
        # strict read answered a spec-defined error class with exit 2
        # and no diagnostics (review round 2). Exit 2 is for the tool
        # being unable to run, and it can run on this.
        source = path.read_bytes().decode("utf-8", errors="surrogateescape")
    except OSError as exc:
        print(f"parser: FAIL: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    try:
        result = parse(source, file=path.name)
    except LarkUnavailable as exc:
        print(f"parser: UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(result.diagnostics.render())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
