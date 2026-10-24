"""The production parser (R12/L5): the frozen grammar, error-tolerant.

WHAT "GENERATED FROM THE SOURCE OF TRUTH" MEANS HERE. This module contains
no grammar. It loads `lang/grammar/rhoform.lark` — the artifact rendered
from `rhoform_syntax.py` and held to it by `make grammar` — and builds
Lark's LALR parser with the contextual lexer and an INDENT/DEDENT postlex,
the same construction `lang/grammar/conformance.py` proved out. The closed
vocabularies are read from the same source-of-truth module (they are
published there as CLOSED_VOCABULARIES precisely so tools can consume
them), and which L8 pragma versions are legal is decided by running the
artifact's own PRAGMA terminal. If the grammar changes, this parser changes
with it, because it carries nothing that could fall behind. The one thing
it does carry, _OLDER_READING, is four edits the artifact must still match
word for word, or the parser refuses to load.

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
pragma pre-check; (3) the restart parse, whose expected-token lists name
no token newer than the file's pragma, and which reads a file older than
0.3 as 0.2 read it first (_parse_as); (4) the soft-keyword heads of a
0.2-style name are retyped to the FREE_NAME they always were; (5)
post-parse file-local checks the prototype also made at parse level:
closed-vocabulary words (RHO1009) and quantity-literal semantics (RHO1010,
via rhoform.quantities), and since 0.3 designators run together
(RHO1018) and reserved words used as names (RHO1019); (6) the
syntax-version gate: one grammar parses every version, and a construct
newer than the pragma is ONE RHO1016 per file whose fix-it rewrites the
pragma to the newest version the file needs. The table-row arity check is
deliberately NOT here — the grammar's own docstring assigns it to the
checker — and neither is anything about what the 0.2 and 0.3 constructs
MEAN (parameter references resolving, range bounds, instances inside
`for`, what an annotation's target names): that is the elaborator's.

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
# inside `(` is what lets a parameter list wrap. `[` is deliberately NOT a
# paren type (decision S-5): an index never wraps, and an unclosed `[` must be
# one error on its own line, not a file joined into one logical line. That
# keeps every bracket-recovery path below `(`-only.
_INDENTER = dict(
    NL_type="_NEWLINE",
    OPEN_PAREN_types=["LPAR"],
    CLOSE_PAREN_types=["RPAR"],
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
    # Syntax 0.2. A declared parameter's type, and a `for` header's callable,
    # whose only legal spelling is `range`. The second is a one-word closed
    # vocabulary rather than a new code: it is the same defect as every
    # other site here (a word outside a fixed list in a NAME position that
    # must stay a NAME, because `range` was never reserved), so it gets the
    # same code, the same params and the same did-you-mean fix-it, and the
    # list is published in CLOSED_VOCABULARIES for constrained decoders.
    "param": ("param_type", 0),
    "for_stmt": ("loop_iterator", 0),
}

# The words the needs-newer-pragma diagnostic names each construct of the
# source of truth's CONSTRUCT_SINCE by (a test holds the two tables to one
# key set). An annotation is named by its own word, `supply` or `draw`. The
# three constructs with no key there are recognized directly by
# _newer_constructs: a `value` whose child is a FREE_NAME (a parameter
# reference, 0.2), a vocabulary word of WORDS_SINCE (a `ground_kind`
# attribute, 0.3) and an endpoint that reaches into a bundle (a member
# access, 0.3).
_CONSTRUCT_PROSE = {
    "import_stmt": "an `import` statement",
    "component_def": "a `component` definition",
    "params": "a parameter list",
    "if_stmt": "an `if` statement",
    "for_stmt": "a `for` loop",
    "array_size": "an array size",
    "index": "an index",
    "annotation": "a `{word}` statement",
    "waiver": "a `waive` statement",
    "rule_override": "a `rule` statement",
    "rule_decl": "a component rule",
    "side_decl": "a `side` declaration",
    "QUOTED_DESIGNATOR": "a quoted designator",
    "WARNING": "a `warning` severity",
    "interface_def": "an `interface` definition",
    "bundle_port_decl": "a bundle port",
    "view_decl": "an interface view",
}
_PARAMETER_REFERENCE = ("a parameter reference", "0.2")
_MEMBER_ACCESS = ("a member access", "0.3")
# The rules whose children spell a connectable point, name and index by
# name and index: since 0.3 the third name, or an index after the second, is
# a member access.
_ENDPOINTS = frozenset({"endpoint", "chain_head"})

# What 0.3 added to the grammar that opens on a token 0.2 already had: a
# bundle port's `=` after `port NAME`, a view's `port` in a component body,
# and a member access's second dot or an index after a dot. The expected
# sets are filtered token by token, which cannot take these out, and the
# parse would carry on into them, so a broken 0.2 line would be reported
# somewhere else than 0.2 reported it. The older reading (_parse_as) is
# therefore the artifact with these four edits made, each to the one rule
# that carries it: (rule, artifact text, what 0.2 had). All four are 0.3,
# like the soft heads, so one older reading serves both.
_OLDER_READING = (
    ("statement", " | bundle_port_decl", ""),
    ("component_def", " | view_decl", ""),
    ("chain_head", '("." NAME index?)*', '("." NAME)?'),
    ("endpoint", '("." NAME index?)*', '("." NAME)?'),
)

# The soft keywords a statement's head may be while it is the name it was
# before 0.3 (`supply = new ...`): the parser retypes them to FREE_NAME, so
# such a 0.2 file keeps its 0.2 tree. The SoT's SOFT_KEYWORDS comment says
# why they are terminals at all.
_SOFT_HEADS = frozenset({"SUPPLY", "DRAW", "WAIVE", "RULE"})
_HEAD_POSITIONS = frozenset({"instance_decl", "chain_head"})

# Where a FREE_NAME names a component's pin rather than a bound name: a
# rule's pins and a side's. Pin names are not bound names (spec 02, Names),
# so a word reserved from 0.3 on may still be one.
_PIN_REFERENCES = frozenset({"rule_body", "side_decl"})

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
    "COMPARE": "a comparison operator",
    # Prose, not a backticked spelling: _describe_token takes a
    # backtick-initial description for the token itself, which made a
    # stray `-` read "unexpected `+` or `-`".
    "INDEX_OP": "an index offset operator",
    # Syntax 0.3. The soft keywords need no entry: each is its word with a
    # keyword boundary, so it is described like a keyword.
    "RULE_WORD": "a rule word",
    "DIAGNOSTIC_CODE": "a diagnostic code",
    "QUOTED_DESIGNATOR": "a quoted designator",
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


def _older_grammar(grammar: str) -> str:
    """The artifact as a file older than 0.3 is parsed: `grammar` with the
    _OLDER_READING edits made. Each must find its text exactly once on its
    rule's line, so an artifact that has moved on fails here, loudly,
    rather than leaving 0.3 in the older reading."""
    lines = grammar.split("\n")
    for rule, text, older in _OLDER_READING:
        at = [index for index, line in enumerate(lines)
              if line.startswith(f"{rule}: ")]
        if len(at) != 1 or lines[at[0]].count(text) != 1:
            raise RuntimeError(  # pragma: no cover - artifact drift
                f"rule `{rule}` in rhoform.lark no longer reads "
                f"`{text}`; revisit _OLDER_READING")
        lines[at[0]] = lines[at[0]].replace(text, older)
    return "\n".join(lines)


_SYNTAX_VERSIONS: tuple[tuple[str, ...], tuple[str, ...]] | None = None


def _versions() -> tuple[tuple[str, ...], tuple[str, ...]]:
    global _SYNTAX_VERSIONS
    if _SYNTAX_VERSIONS is None:
        sot = _load_sot()
        _SYNTAX_VERSIONS = (tuple(sot.SYNTAX_VERSIONS),
                            tuple(sot.FROZEN_SYNTAX_VERSIONS))
    return _SYNTAX_VERSIONS


def syntax_versions() -> tuple[str, ...]:
    """The syntax versions this toolchain parses, as the grammar source of
    truth lists them (`0.1`, `0.2`, `0.3`). Needs no lark: the package
    layer checks manifests against them before anything is parsed."""
    return _versions()[0]


def frozen_syntax_versions() -> tuple[str, ...]:
    """The syntax versions that are frozen: every one but those the source
    of truth marks unfrozen (decision OD8), which may still change shape and
    so are not announced to a manifest."""
    return _versions()[1]


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def normalize(source: str) -> str:
    """The one normalization the grammar is owed: a final newline token.

    Identical to conformance.normalize, and a property of the reader
    rather than the language — every statement really is
    newline-terminated in the token stream."""
    return source if source.endswith("\n") else source + "\n"


@dataclass
class _Loaded:
    parser: object
    demoted: object       # the older reading: soft heads read as names,
                          # and _OLDER_READING's edits made
    pragma_text: str      # the CURRENT header: what a new file and a fix-it use
    pragma_re: object     # the artifact's own PRAGMA terminal, compiled
    pragma_prefix: str    # the header minus its version
    current_version: str
    keyword_of: dict
    vocabularies: dict
    quantity_re: object  # the SoT's full five-form literal pattern
    since: dict          # terminal name -> the version that introduced it
    construct_since: dict
    words_since: dict
    reserved_since: dict
    pin_names: frozenset  # what a rule's pin position takes, by terminal


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

    from lark import Token

    indenter = type("RhoformIndenter", (Indenter,), _INDENTER)
    grammar = GRAMMAR_PATH.read_text(encoding="utf-8")
    parser = Lark(
        grammar,
        parser="lalr",
        postlex=indenter(),
        start="start",
        propagate_positions=True,
    )

    def as_name(token):
        return Token.new_borrow_pos("FREE_NAME", str(token), token)

    # A file older than the soft keywords is read first by a lexer that
    # hands each one on as the FREE_NAME it was then, over the grammar with
    # 0.3's older-token openings taken out: the parse a 0.2 toolchain made
    # of it, diagnostics and all (see _parse_as).
    demoted = Lark(
        _older_grammar(grammar),
        parser="lalr",
        postlex=indenter(),
        start="start",
        propagate_positions=True,
        lexer_callbacks={name: as_name for name in _SOFT_HEADS},
    )
    # One table below describes the tokens of both readings, so the edits
    # must leave every terminal the older one has named as it was.
    terminals = {terminal.name: terminal.pattern
                 for terminal in parser.terminals}
    if any(terminals.get(terminal.name) != terminal.pattern
           for terminal in demoted.terminals):
        raise RuntimeError(  # pragma: no cover - artifact drift
            "the older reading of rhoform.lark names a terminal differently "
            "from the grammar; revisit _OLDER_READING")

    sot = _load_sot()
    pragma_pattern = None
    keyword_of = {}
    since = {}
    for terminal in parser.terminals:
        pattern = terminal.pattern
        value = getattr(pattern, "value", "")
        if terminal.name == "PRAGMA":
            # The header check below runs the artifact's OWN terminal, so
            # which versions are legal is decided by the generated grammar
            # and nowhere else — this parser holds no second copy.
            pragma_pattern = value
        elif pattern.type == "re":
            match = _KEYWORD_PATTERN.match(value)
            if match:
                keyword_of[terminal.name] = match.group(1)
        # Which version introduced the token, by its word, its spelling or
        # its name (the SoT keys each kind its own way): what the expected
        # sets are filtered by.
        version = (sot.KEYWORDS_SINCE.get(keyword_of.get(terminal.name))
                   or (sot.TERMINALS_SINCE.get(value)
                       if pattern.type == "str" else None)
                   or sot.TERMINALS_SINCE.get(terminal.name))
        if version is not None:
            since[terminal.name] = version

    pragma_re = re.compile(pragma_pattern or "(?!)")
    # Drift guard, both directions: every version the source of truth
    # lists must be a header the artifact accepts, and the artifact may
    # accept nothing the source of truth does not render.
    if (pragma_pattern != sot.TERMINALS["PRAGMA"]
            or not all(pragma_re.fullmatch(text)
                       for text in sot.PRAGMA_TEXTS)
            or not pragma_re.fullmatch(sot.PRAGMA_TEXT)):
        raise RuntimeError(  # pragma: no cover - artifact drift
            "the PRAGMA terminal in rhoform.lark does not match the source "
            "of truth's pragma versions; regenerate the artifacts"
        )
    _CACHE = _Loaded(
        parser=parser,
        demoted=demoted,
        pragma_text=sot.PRAGMA_TEXT,
        pragma_re=pragma_re,
        pragma_prefix=sot.PRAGMA_PREFIX,
        current_version=sot.SYNTAX_VERSION,
        keyword_of=keyword_of,
        vocabularies=dict(sot.CLOSED_VOCABULARIES),
        quantity_re=re.compile(sot.LEXER_QUANTITY),
        since=since,
        construct_since=dict(sot.CONSTRUCT_SINCE),
        words_since={vocabulary: dict(words) for vocabulary, words
                     in sot.WORDS_SINCE.items()},
        reserved_since=dict(sot.RESERVED_SINCE),
        pin_names=frozenset(
            {"FREE_NAME"} | {name for name, word in keyword_of.items()
                             if word in sot.PIN_KEYWORDS}),
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
    # The author's exact bytes, and how far tree positions sit past them.
    # The shift is nonzero only when the pragma pre-check prepended a
    # header, and that always comes with an RHO1005 error, so on an `ok`
    # result it is 0 — but a consumer subtracting it is correct either
    # way, which is what lets the elaborator's spans be byte-true without
    # depending on that coincidence.
    data: bytes = b""
    shift: int = 0

    @property
    def ok(self) -> bool:
        return self.tree is not None and not self.diagnostics.has_errors

    def span_of(self, node) -> Span:
        """The node's span over the author's bytes, first token to last.

        A statement's `meta.end_pos` runs on through the trailing
        `_NEWLINE` token, which swallows the next line's indentation, a
        trailing `# comment` and any comment-only lines after it, so it
        is not used. The extent is instead taken from what the tree
        keeps: every named token, plus the bracketed subtrees
        (`arguments`, `net_attributes`, and syntax 0.2's `params`,
        `array_size` and `index`) whose meta is exact and is the only
        record of their brackets. Tree positions are character
        offsets, which equal byte offsets because a non-ASCII byte stops
        the parse before a tree exists.
        """
        start, end = _extent(node)
        start = max(0, min(start - self.shift, len(self.data)))
        end = max(start, min(end - self.shift, len(self.data)))
        return span_from_bytes(self.file, self.data, start, end)


_BRACKETED = frozenset(
    {"arguments", "net_attributes", "params", "array_size", "index",
     "member_path"})


def _extent(node) -> tuple[int, int]:
    """(first start, last end) over a subtree's kept tokens, in tree
    positions. Iterative, so a deep tree cannot exhaust the stack."""
    start = end = None
    stack = [node]
    while stack:
        current = stack.pop()
        children = getattr(current, "children", None)
        if children is None:
            lo, hi = current.start_pos, current.end_pos
        elif current.data in _BRACKETED and not current.meta.empty:
            lo, hi = current.meta.start_pos, current.meta.end_pos
        else:
            stack.extend(children)
            continue
        if lo is None or hi is None:
            continue
        start = lo if start is None else min(start, lo)
        end = hi if end is None else max(end, hi)
    if start is None:
        meta = getattr(node, "meta", None)
        position = getattr(meta, "start_pos", 0) or 0
        return position, position
    return start, end


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


def _expected_list(names, keyword_of: dict, pin_names=frozenset()) -> str:
    names = set(names)
    described = set()
    if pin_names and pin_names <= names:
        # A component rule's pin position (0.3) takes a name or any keyword
        # but `from` and `to`, which is one thing to ask for, not twenty-six.
        names -= pin_names
        described.add("a pin name")
    described |= {_describe_terminal(name, keyword_of) for name in names}
    described = sorted(described)
    return ", ".join(described) if described else "nothing (internal state)"


def _for_version(names, loaded: "_Loaded", version: str) -> set:
    """The expected terminals a file declaring `version` may be told about
    (AMB-146 #2): one grammar serves every version, so the parser's own set
    can name a token only a newer version has — `import` to a 0.1 file,
    `supply` to a 0.2 one — and following that hint draws RHO1016. A token
    newer than the pragma is dropped. When nothing would be left the parse
    stands inside a newer construct already, which only its own tokens can
    continue, and the set is kept whole rather than claim nothing fits."""
    key = _version_key(version)
    kept = {name for name in names
            if _version_key(loaded.since.get(name, "0.1")) <= key}
    return kept or set(names)


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


@dataclass
class _Header:
    """The author's own, legal pragma line: its version and where the
    version sits in the author's bytes (for the needs-newer-pragma fix-it,
    which rewrites exactly those bytes)."""

    version: str
    version_start: int
    version_end: int


def _pragma_precheck(file: str, source: str, data: bytes, loaded: _Loaded,
                     sink: Diagnostics) -> tuple[str, int, "_Header | None"]:
    """Check the L8 header; return (text to parse, offset shift, header).

    The first content line — not blank, not a comment (a `#` line whose
    word is not `pragma`; `#pragmatic` is a comment, per the frozen
    boundary) — must be exactly a pragma the artifact's PRAGMA terminal
    accepts: one per implemented syntax version. When it is, the source
    parses as-is, the shift is 0, and the header names the version. When it
    is not, ONE RHO1005 is emitted with a machine-applicable fix-it that
    writes the CURRENT version, and the parse input becomes that header plus
    the source (with a wrong header line blanked), so the body is still
    checked — as the current version, since that is what the fix-it makes
    it; the returned shift translates every parse-input offset back onto
    the author's bytes, and the header is None.
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

    if line is not None and loaded.pragma_re.fullmatch(line.strip()):
        # Prescan has passed, so the text is ASCII and a character offset
        # is a byte offset.
        start = offset + (len(line) - len(line.lstrip(" ")))
        version = line.strip()[len(loaded.pragma_prefix):]
        version_start = start + len(loaded.pragma_prefix)
        return source, 0, _Header(version, version_start,
                                  version_start + len(version))

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
        return expected + "\n" + blanked, len(expected) + 1, None

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
    return expected + "\n" + source, len(expected) + 1, None


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
                   loaded: _Loaded, parser, sink: Diagnostics, version: str):
    """Parse with `parser`, reporting and blanking one defect per round.
    Returns the final tree, or None when recovery was abandoned. `version`
    is the syntax version the file is checked as, which bounds what an
    expected set may name."""
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

    def author_text(a: int, b: int) -> str:
        """The AUTHOR's bytes for [a, b) of the (shifted) parse text.

        Structured params must quote what the author wrote; a literal
        read from `parse_text` after a blanking round quotes recovery's
        own spaces (review round 4)."""
        lo = max(0, min(a - shift, len(data)))
        hi = max(lo, min(b - shift, len(data)))
        return data[lo:hi].decode("utf-8", "surrogateescape")

    blanked_lines: dict[int, int] = {}
    # Headers whose subordinate lines RECOVERY blanked. Only these may be
    # silenced when the parser later wants the block they no longer
    # introduce — an author's own genuinely empty block, with unrelated
    # errors elsewhere, must still be reported, so "we emptied it" is
    # tracked precisely rather than inferred from any-blanking-happened.
    suspect_headers: set[int] = set()
    # Lines whose unterminated string was reported (RHO1004) and blanked
    # to their end. What is left of such a line is the string's shadow: the
    # statement around it can no longer be complete, and charging it with
    # the token it now lacks asked the author for "a string", the very
    # thing the line was writing (AMB-137 #3).
    string_lines: set[int] = set()
    baseline = len(sink)

    def consume(start: int, end: int, *, destroys_statement: bool) -> None:
        """Blank [start, end) and carry EVERY piece of shadow bookkeeping.

        THE ONE BLANKING PATH. Six of the eighteen findings across five
        review rounds were a single shape: a handler blanked text and
        carried some but not all of the bookkeeping its siblings carried.
        The rule was written in comments at six call sites, so every new
        site re-derived it and one more site got it wrong. It lives in one
        function now, where a handler cannot carry a subset of it.

        Three steps:

        1. The span is blanked.
        2. The statement's subordinate block goes with it — always when
           the blank destroyed the statement outright, and otherwise when
           the blank emptied the line, which destroys it just as surely.
           A block belongs to its statement; an orphan re-anchors the
           Indenter and draws one diagnostic per line (review round 1).
        3. When the line is now empty it is recorded in `blanked_lines`,
           so the $END guard can tell recovery's own emptiness from the
           author's, and its enclosing header joins `suspect_headers`, so
           the block WE emptied is never charged to the author.

        A blank that leaves residue on the line takes step 1 alone: the
        statement still stands, and the next round diagnoses what is left
        of it (this is what pins r12's second diagnostic).
        """
        nonlocal parse_text
        line_start, line_end = _line_bounds(parse_text, start)
        # Read BEFORE blanking: an all-space line misreports its depth.
        indent = _indent_of(parse_text, line_start)
        parse_text = _blank(parse_text, start, end)
        emptied = not parse_text[line_start:line_end].strip()
        if destroys_statement or emptied:
            parse_text = _blank_block(parse_text, line_start, indent)
        if not emptied:
            return
        blanked_lines[line_start] = indent
        parent = _parent_header(parse_text, line_start, indent)
        if parent is not None:
            suspect_headers.add(parent)

    def drain_unclosed_brackets(*, report: bool) -> None:
        """Blank every unclosed `(`. Name it only on the author's text.

        Inside `(` a line break is not layout, so one forgotten closer
        swallows every later line into a single logical line and the parse
        errors blame those innocent lines — and the EOF-flushed DEDENT
        then lands on text recovery already blanked, where blanking makes
        no progress (review round 4 measured eighteen byte-identical
        diagnostics). The prototype lexer had exactly this check.

        `report=True` runs ONCE, before any handler has edited anything.
        An imbalance in that text is the AUTHOR's, and earns RHO1015 plus
        the statement's wrapped continuation — inside a bracket those
        deeper-indented lines are the same logical line, and each draws
        its own spurious diagnostic once the opener is gone (round 5).

        Every later pass runs on text `consume()` has mutated, where an
        imbalance may be RECOVERY'S: blanking the line that carried the
        closer leaves the opener dangling. Blanking it still stops the
        flood; NAMING it does not, and is false — "`(` opened here is
        never closed" is a claim about a source whose brackets balance,
        and it sorts first, so a repair loop closes a parenthesis that
        was never open (round 7 measured 49 false RHO1015 across 7,848
        bracket-balanced mutants).

        Both passes CONSUME the same way — the opener through its line
        end and the deeper-indented block beneath it — because inside a
        bracket those lines are one logical line and each draws its own
        spurious diagnostic once the opener is gone (round 5). They differ
        only in whether they say anything. An independent defect inside
        that block is its shadow, the same rule every emptied statement
        follows.
        """
        nonlocal parse_text
        while True:
            unclosed = _first_unclosed_bracket(parse_text)
            if unclosed is None:
                return
            opener, bracket = unclosed
            _, opener_line_end = _line_bounds(parse_text, opener)
            if report:
                sink.add("RHO1015", {"bracket": bracket},
                         primary=span_at(opener, opener + 1))
                if len(sink) - baseline >= _RECOVERY_LIMIT:
                    return
            consume(opener, opener_line_end, destroys_statement=True)

    # The author's own brackets, judged on the author's own bytes.
    drain_unclosed_brackets(report=True)

    # Iterations, not diagnostics: silent blanking rounds (orphaned blocks,
    # emptied headers) consume iterations without emitting, and every round
    # blanks at least one character, so line-count-plus-limit terminates.
    budget = parse_text.count("\n") + _RECOVERY_LIMIT + 4
    previous_text = None
    for _ in range(budget):
        # Both guards live at the TOP so no handler's `continue` can slip
        # past them: the missing-block path did exactly that, emitting
        # thirty diagnostics past a limit of twenty (review round 5).
        if len(sink) - baseline >= _RECOVERY_LIMIT:
            return None
        if parse_text == previous_text:
            # No byte changed since the last round: the error position
            # sits on text recovery already blanked, and the next round
            # would emit the identical diagnostic — round 4 measured
            # eighteen of them. Every handler is SUPPOSED to blank
            # something; this is the failsafe for the paths that forget.
            return None
        previous_text = parse_text
        drain_unclosed_brackets(report=False)
        try:
            return parser.parse(parse_text)
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
                string_lines.add(line_start)
                consume(pos, line_end, destroys_statement=False)
            elif re.match(r"#pragma(?![A-Za-z0-9_])", parse_text[pos:]):
                # A `#pragma` the lexer refuses is mid-line (the header
                # pre-check settled line-initial ones): one diagnostic
                # for the frozen decision, not one per character of it.
                sink.add("RHO1013", {}, primary=span_at(pos, line_end))
                consume(pos, line_end, destroys_statement=False)
            elif quantity_tail is not None:
                # ` +/- 1%` after a plain quantity lexes as nothing, so
                # the generic path charged one diagnostic per character
                # of the operator. The defect is the literal's FORM in a
                # plain-quantity position; say that once, with the whole
                # literal in the span, and blank only the unconsumed tail.
                match_start, match_end, _ = quantity_tail
                sink.add("RHO1012",
                         {"literal": author_text(match_start, match_end)},
                         primary=span_at(match_start, match_end))
                consume(pos, match_end, destroys_statement=False)
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
                head, blank_end, reason = operator
                sink.add(
                    "RHO1010",
                    {"literal": author_text(head, blank_end),
                     "reason": reason},
                    primary=span_at(head, blank_end),
                )
                consume(pos, blank_end, destroys_statement=False)
            else:
                # A mid-line `+/-` with no quantity head (a string head,
                # say) is still ONE junk unit, not three characters
                # (review round 4, the genus's last visible instance).
                unit = ("+/-" if parse_text[pos:pos + 3] == "+/-"
                        else char)
                sink.add("RHO1011", {"character": f"`{unit}`"},
                         primary=span_at(pos, pos + len(unit)))
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
                    consume(line_start, line_end, destroys_statement=True)
                else:
                    consume(pos, pos + len(unit), destroys_statement=False)
        except UnexpectedToken as exc:
            token = exc.token
            expected_names = set(exc.accepts or exc.expected)
            expected = _expected_list(
                _for_version(expected_names, loaded, version),
                loaded.keyword_of, loaded.pin_names)
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

            start, end = _line_bounds(parse_text,
                                      min(pos, len(parse_text) - 1))
            if token.type != "$END" and start in string_lines \
                    and parse_text[start:end].strip():
                # What an unterminated string left of its line: silence,
                # and the line goes, with its block, as any broken
                # statement's does. Once the line is empty a layout token
                # that lands on it is the next rule's to judge.
                consume(start, end, destroys_statement=True)
                continue

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
                    start, end = _line_bounds(parse_text, header)
                    consume(start, end, destroys_statement=True)
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
            if token.type == "_INDENT":
                # Unexpected indentation names the indentation: the spaces
                # from the line's start to its first content column, where
                # `pos` stays for the orphan search. An insertion point
                # here (both ends at end_pos) named none of the bytes it
                # complains about (AMB-135 #1). An unexpected _DEDENT keeps
                # its insertion point, the place a block was owed.
                primary = span_at(start, pos)
            else:
                primary = span_at(
                    pos,
                    token.end_pos if token.end_pos is not None else pos + 1,
                )
            sink.add(
                "RHO1006",
                {"found": _describe_token(token, loaded.keyword_of),
                 "expected": expected},
                primary=primary,
            )
            # The blanked statement's subordinate block goes with it,
            # UNCONDITIONALLY: a reactive rule that waited for the block's
            # INDENT to be rejected missed the case where the broken
            # statement led its block — the Indenter then established the
            # enclosing level at the orphan's own depth and charged it one
            # diagnostic per line (review round 1). A statement's block
            # belongs to the statement; when the line had no block, this
            # blanks nothing.
            consume(start, end, destroys_statement=True)
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
            # Its block goes with it, same rule as a parse-error line:
            # round 2's review found the flood the round-1 fix removed
            # from the UnexpectedToken path alive and well on this one.
            consume(start, end, destroys_statement=True)
        except Exception:  # pragma: no cover - lark internals
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
            elif char == "(":
                depth += 1
            elif char == ")":
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
    """(head_start, blank_end, reason) for a `+/-` at `pos` whose
    literal never became a full form, or None. The literal PARAM is the
    caller's to build — from the author's bytes, not from `text`, which
    may already carry recovery's blanks (review round 4).

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
            return (line_start + match.start(), blank_end, reason)
    return None


def _continues_statement(text: str, opener: int, line_start: int,
                         reach: dict[int, int]) -> bool:
    """Is the line at `line_start` the same statement as the opener's?

    The same physical line, or a wrapped continuation: every content line
    from the opener's line to this one is indented deeper than the
    opener's line — the block model `_blank_block` uses, so the scanner
    and the shadow rule agree on where a statement ends. `reach` memoizes,
    per opener and per scan, the start of the first content line that
    ends its run, so a long continuation is walked once rather than once
    per leftover closer."""
    opener_start, opener_end = _line_bounds(text, opener)
    if opener_start == line_start:
        return True
    if opener not in reach:
        indent = _indent_of(text, opener_start)
        limit = len(text)
        position = opener_end + 1
        while position < len(text):
            start, end = _line_bounds(text, position)
            content = text[start:end].strip()
            if (content and not content.startswith("#")
                    and _indent_of(text, start) <= indent):
                limit = start
                break
            position = end + 1
        reach[opener] = limit
    return line_start < reach[opener]


def _first_unclosed_bracket(text: str):
    """(offset, bracket) of the first `(` never closed, or None.

    Mirrors the lexer's reality: strings end at their line, comments run
    to end of line, and a closer with no opener is someone else's error
    (the depth floors at zero, matching the prototype lexer).

    `(` only. Since syntax 0.2 `[` and `]` are tokens (array sizes and
    indexes), but they do NOT suspend layout — `_INDENTER` names only
    LPAR/RPAR as paren types, by decision S-5 — so an unclosed `[` joins
    nothing and is an ordinary unexpected-token error on its own line.
    Scanning `[` here would make RHO1015 assert a mechanism that cannot
    run (review round 6 found exactly that when `[` was an illegal
    character)."""
    stack: list[tuple[int, str]] = []
    reach: dict[int, int] = {}
    position = 0
    while position < len(text):
        start, end = _line_bounds(text, position)
        in_string = False
        quote_at = start
        for index in range(start, end):
            char = text[index]
            if in_string:
                in_string = char != '"'
            elif char == '"':
                in_string, quote_at = True, index
            elif char == "#":
                break
            elif char == "(":
                stack.append((index, char))
            elif char == ")" and stack:
                stack.pop()
        if in_string:
            # An unterminated string is a LEXICAL ERROR at the opening
            # quote, not a string that ends at the newline — STRING is
            # single-line and cannot span one. Scanning past it swallowed
            # the rest of the line, INCLUDING a `)` that closes an open
            # call, and naming that call's `(` as unclosed preempted the
            # true RHO1004 with advice whose application reproduced the
            # identical diagnostic (review round 7).
            #
            # Round 7 answered by giving up on the WHOLE FILE, which
            # silenced RHO1015 for the entire compile whenever any line
            # ended inside a string — and inside the unnamed `(` every
            # later line was one logical line again, the round-4 flood
            # (round 8 measured twenty innocent `port` lines blamed, both
            # real defects unnamed, and no tree past the recovery limit).
            # Only the SWALLOWED TAIL is fiction, and it is read the way the
            # author meant it: its own `(` and `)` pair off among
            # themselves (a bracketed interval inside the tail closes
            # itself), and a closer left over was meant for an opener
            # outside the string — but only one whose STATEMENT this line
            # continues: the same line, or a wrapped continuation under
            # the block model `_blank_block` uses. Spending it on whatever
            # opener was innermost let `package = "0402)` two statements
            # below an unclosed call close THAT call: the once-only
            # reporting pass then saw balance, named nothing, and the
            # flood this rule exists to prevent came back — 98 of 71,391
            # mutants in round 8's focused pass, every one named correctly
            # at round 6. A leftover `)` on a sibling-indent line was meant
            # for something the scanner cannot see, and the opener above
            # stays as unclosed as it is. Everything before the quote — on
            # this line and above it — is text the lexer reaches, so an
            # opener there that the tail does not close stays on the stack
            # for a later line, or for RHO1015. (Round 8's first two cuts
            # got both halves wrong in turn: dropping this line's own
            # openers as "unknowable" lost 94 true RHO1015 across the
            # two-edit sweep, and counting every `)` in the tail lost 64
            # more to intervals that had closed themselves.)
            depth_inside = 0
            for char in text[quote_at:end]:
                if char == "(":
                    depth_inside += 1
                elif char == ")":
                    if depth_inside:
                        depth_inside -= 1
                    elif stack and _continues_statement(
                            text, stack[-1][0], start, reach):
                        stack.pop()
        position = end + 1
    return stack[0] if stack else None


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
        return ParseResult(tree=None, diagnostics=sink, file=file, data=data)

    parse_text, shift, header = _pragma_precheck(file, source, data, loaded,
                                                 sink)
    # A file with no legal header is parsed as the current version, which
    # is what RHO1005's fix-it writes.
    version = loaded.current_version if header is None else header.version
    tree = _parse_as(file, data, parse_text, shift, loaded, sink, version)

    if tree is not None:
        _retype_soft_heads(tree)
        _postparse(file, data, shift, tree, loaded, sink, version)
        _version_gate(file, data, shift, tree, loaded, sink, header)
    return ParseResult(tree=tree, diagnostics=sink, file=file, data=data,
                       shift=shift)


def _parse_as(file: str, data: bytes, parse_text: str, shift: int,
              loaded: _Loaded, sink: Diagnostics, version: str):
    """The restart parse, as the file's version reads it.

    A file declaring a version older than the soft keywords keeps the parse
    it had (spec 01): its `supply`, `draw`, `waive` and `rule` are names,
    so a broken line they head is reported where 0.2 reported it, and the
    expected set is 0.2's — not a 0.3 statement's, whose hint (`within`)
    only draws RHO1016 when followed. The same holds for what 0.3 opens
    with an older token (_OLDER_READING): `port p` missing its role is
    asked for the role alone, not for a bundle port's `=`, and `r.b.` is
    reported at its second dot. So it is parsed with the soft heads
    demoted and those openings taken out first. A clean parse is the 0.2
    tree. A failed one is tried once more with the whole grammar: if the
    file then parses, its lines were 0.3 statements, which the version gate
    reports as one RHO1016; if not, the 0.2 reading's diagnostics stand."""
    soft = min((loaded.since[name] for name in _SOFT_HEADS),
               key=_version_key)
    if _version_key(version) >= _version_key(soft):
        return _restart_parse(file, data, parse_text, shift, loaded,
                              loaded.parser, sink, version)
    older = Diagnostics()
    tree = _restart_parse(file, data, parse_text, shift, loaded,
                          loaded.demoted, older, version)
    if tree is None or len(older):
        newer = Diagnostics()
        retry = _restart_parse(file, data, parse_text, shift, loaded,
                               loaded.parser, newer, version)
        if retry is not None and not len(newer):
            return retry
    sink.extend(older)
    return tree


def _retype_soft_heads(tree) -> None:
    """A soft keyword that heads an instance declaration or a chain is the
    name it was before 0.3: give it back the FREE_NAME type, so a 0.2 file
    that names an instance `supply` has the tree it always had. Only the
    lexer told the two apart (the SoT's SOFT_KEYWORDS says why)."""
    from lark import Token

    work = [tree]
    while work:
        node = work.pop()
        children = getattr(node, "children", None)
        if children is None:
            continue
        if node.data in _HEAD_POSITIONS and children \
                and getattr(children[0], "type", None) in _SOFT_HEADS:
            children[0] = Token.new_borrow_pos("FREE_NAME", str(children[0]),
                                               children[0])
        work.extend(child for child in children if hasattr(child, "data"))


def _token_span(file: str, data: bytes, shift: int, token) -> Span:
    start = (token.start_pos or 0) - shift
    end = (token.end_pos if token.end_pos is not None else start) - shift
    start = max(0, min(start, len(data)))
    end = max(start, min(end, len(data)))
    return span_from_bytes(file, data, start, end)


def _postparse(file: str, data: bytes, shift: int, tree, loaded: _Loaded,
               sink: Diagnostics, version: str) -> None:
    """File-local checks past the grammar: vocabularies and quantities,
    and since 0.3 designator runs and reserved words."""
    key = _version_key(version)
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
                    # A word newer than the pragma is still a word (it
                    # draws RHO1016, not this), but it is no repair: a
                    # did-you-mean naming it would draw RHO1016, and as a
                    # second close match it hid the one that is (F3).
                    since = loaded.words_since.get(vocabulary, {})
                    candidates = tuple(
                        entry for entry in allowed
                        if _version_key(since.get(entry, "0.1")) <= key)
                    span = _token_span(file, data, shift, word)
                    sink.add(
                        "RHO1009",
                        {"vocabulary": vocabulary, "word": str(word)},
                        primary=span,
                        fixits=_closest_fixit(str(word), candidates, span),
                    )
        if node.data == "net_attribute":
            _ground_kind_value(file, data, shift, node, loaded, sink)
    # A designator run needs a separator from the version that can spell
    # its other reading, the quoted designator (AMB-139: 0.1 and 0.2 keep
    # the old lexing).
    if _version_key(version) >= _version_key(
            loaded.construct_since["QUOTED_DESIGNATOR"]):
        _designator_runs(file, data, shift, tree, sink)
    _reserved_names(file, data, shift, tree, loaded, sink, version)
    # Tree.scan_values recurses once per level, and if/for nest without
    # bound; this is the same left-to-right walk on an explicit stack.
    work = [tree]
    while work:
        token = work.pop()
        children = getattr(token, "children", None)
        if children is not None:
            work.extend(reversed(children))
            continue
        if getattr(token, "type", None) not in _QUANTITY_TOKEN_TYPES:
            continue
        try:
            parse_quantity(str(token))
        except QuantityError as exc:
            sink.add(
                "RHO1010",
                {"literal": str(token), "reason": exc.reason},
                primary=_token_span(file, data, shift, token),
            )


def _comment_start(line: str):
    """Index of the `#` that opens a trailing comment on `line`, or None.
    Strings are single-line and cannot contain `"`, so a toggle suffices."""
    in_string = False
    for index, char in enumerate(line):
        if char == '"':
            in_string = not in_string
        elif char == "#" and not in_string:
            return index
    return None


def _content_end(data: bytes, start: int, end: int) -> int:
    """The end of the author's content in [start, end): trailing blank
    lines, indentation, comment-only lines and a trailing comment removed,
    since a layout token's borrowed position may have reached across all
    of them."""
    text = data[start:end].decode("utf-8", "surrogateescape")
    while True:
        text = text.rstrip(" \n")
        line_start = text.rfind("\n") + 1
        cut = _comment_start(text[line_start:])
        if cut is None:
            return start + len(text)
        text = text[:line_start + cut]


def _newer_constructs(data: bytes, shift: int, tree,
                      loaded: _Loaded) -> list[tuple[int, int, str, str]]:
    """(start, end, construct, version) for each construct of `tree` that
    some version after 0.1 introduced, as author byte offsets, ordered by
    start, then longest first. A construct is a node whose rule, or a token
    whose terminal, the SoT's CONSTRUCT_SINCE names, plus the three it
    cannot name: a parameter reference, a vocabulary word of WORDS_SINCE and
    a member access."""
    found = []
    work = [tree]
    while work:
        node = work.pop()
        if not hasattr(node, "data"):
            version = loaded.construct_since.get(node.type)
            if version is not None:
                start = max(0, node.start_pos - shift)
                found.append((start, max(start, node.end_pos - shift),
                              _CONSTRUCT_PROSE[node.type], version))
            continue
        construct = version = None
        if node.data in loaded.construct_since:
            version = loaded.construct_since[node.data]
            construct = _CONSTRUCT_PROSE[node.data]
            if "{word}" in construct:  # an annotation, by its own word
                construct = construct.format(word=node.children[0])
        elif node.data == "value" and any(
                getattr(child, "type", None) == "FREE_NAME"
                for child in node.children):
            construct, version = _PARAMETER_REFERENCE
        elif node.data in _ENDPOINTS and _member_access(node):
            construct, version = _MEMBER_ACCESS
        elif node.data in _VOCAB_SITES:
            vocabulary, index = _VOCAB_SITES[node.data]
            names = [child for child in node.children
                     if getattr(child, "type", None) == "NAME"]
            word = str(names[index]) if index < len(names) else None
            version = loaded.words_since.get(vocabulary, {}).get(word)
            if version is not None:
                construct = f"a `{word}` attribute"
        if construct is not None and not node.meta.empty:
            # The node's meta counts the anonymous `(` `)` `[` `]` its
            # tokens do not (an empty parameter list has NO tokens in the
            # tree), but also a trailing DEDENT or NEWLINE, whose position
            # is borrowed from the newline run after the construct — so its
            # end is walked back over that run before it names any author
            # bytes.
            start = max(0, node.meta.start_pos - shift)
            end = _content_end(data, start,
                               max(start, node.meta.end_pos - shift))
            found.append((start, end, construct, version))
        work.extend(node.children)
    found.sort(key=lambda item: (item[0], -item[1], item[2]))
    return found


def _member_access(node) -> bool:
    """Whether an endpoint reaches into a bundle (0.3): a third name, or an
    index after its second. `a`, `a.b`, `a[i]` and `a[i].b` are 0.1 and
    0.2 shapes."""
    names = 0
    for child in node.children:
        if hasattr(child, "data"):  # an index
            if names >= 2:
                return True
        else:
            names += 1
    return names > 2


def _version_gate(file: str, data: bytes, shift: int, tree, loaded: _Loaded,
                  sink: Diagnostics, header: "_Header | None") -> None:
    """Constructs newer than the pragma: ONE diagnostic per file.

    One grammar parses every version (decision S-2), so this is where 0.1
    stays 0.1 and 0.2 stays 0.2. One diagnostic, not one per construct,
    because there is one defect — the header — and one repair: its fix-it
    rewrites the version to the newest one any construct in the file needs
    (`required`). That is machine-applicable when `required` only adds to
    the file, so it means nothing different under it. 0.3 does not only
    add: it refuses a designator run 0.2 read as separate designators
    (RHO1018), so the fix-it also spaces each run out, which is the old
    reading spelled for both; and it reserves names 0.2 bound (RHO1019),
    which no edit can choose a new name for, so then it is needs-review
    and says which. The primary
    span is the FIRST construct that needs `required`, so the author sees
    why and the message is true of it; `count` says how many constructs
    the pragma refuses, so nobody mistakes the first for the only one. A
    file with no legal header (`header` None) was already given RHO1005
    and is parsed as the current version, so it draws nothing here.
    """
    if header is None:
        return
    declared = _version_key(header.version)
    found = [item for item in _newer_constructs(data, shift, tree, loaded)
             if _version_key(item[3]) > declared]
    if not found:
        return
    required = max((item[3] for item in found), key=_version_key)
    start, end, construct, _ = next(item for item in found
                                    if item[3] == required)
    primary = span_from_bytes(file, data, start, end)
    version_span = span_from_bytes(file, data, header.version_start,
                                   header.version_end)

    def newly(since: str) -> bool:
        return declared < _version_key(since) <= _version_key(required)

    edits = [Edit(version_span, required)]
    if newly(loaded.construct_since["QUOTED_DESIGNATOR"]):
        edits += [Edit(span, " ".join(str(part) for part in run))
                  for span, run in _runs(file, data, shift, tree)]
    reserved = {word for word, since in loaded.reserved_since.items()
                if newly(since)}
    bound = sorted({str(token) for token in _names_in(tree, reserved)})
    message = f"declare syntax {required}: `{loaded.pragma_prefix}{required}`"
    applicability = "machine-applicable"
    if len(edits) > 1:
        message += (f", spacing out the designators that run together as "
                    f"{header.version} reads them")
    if bound:
        words = ", ".join(f"`{word}`" for word in bound)
        message += (f", then rename {words}, which {required} reserves and "
                    f"this file binds as a name")
        applicability = "needs-review"
    elif len(edits) == 1:
        message += f" (it only adds to {header.version})"
    sink.add(
        "RHO1016",
        {"construct": construct, "required": required,
         "declared": header.version, "count": len(found)},
        primary=primary,
        fixits=(FixIt(message, applicability, tuple(edits)),),
    )


def _ground_kind_value(file: str, data: bytes, shift: int, node,
                       loaded: _Loaded, sink: Diagnostics) -> None:
    """A `ground_kind` attribute's string names one of the ground kinds
    (RHO1009, vocabulary `ground_kind`): the word inside the quotes is
    checked, and a did-you-mean fix-it rewrites the whole string."""
    names = [child for child in node.children
             if getattr(child, "type", None) == "NAME"]
    strings = [child for child in node.children
               if getattr(child, "type", None) == "STRING"]
    if not names or str(names[0]) != "ground_kind" or not strings:
        return
    word = str(strings[0])[1:-1]
    allowed = loaded.vocabularies["ground_kind"]
    if word in allowed:
        return
    span = _token_span(file, data, shift, strings[0])
    fixits = tuple(
        FixIt(fixit.message, fixit.applicability,
              tuple(Edit(edit.span, f'"{edit.replacement}"')
                    for edit in fixit.edits))
        for fixit in _closest_fixit(word, allowed, span))
    sink.add("RHO1009", {"vocabulary": "ground_kind", "word": word},
             primary=span, fixits=fixits)


def _runs(file: str, data: bytes, shift: int, tree):
    """(span, tokens) for each run of designators that touch, `01` lexed as
    `0` then `1` and `1A` as `1` then `A`, in source order."""
    for node in tree.iter_subtrees_topdown():
        if node.data != "pin_decl":
            continue
        tokens = [designator.children[0]
                  for designator in node.children
                  if getattr(designator, "data", None) == "designator"]
        run = tokens[:1]
        for token in tokens[1:] + [None]:
            if token is not None and run and \
                    run[-1].end_pos == token.start_pos:
                run.append(token)
                continue
            if len(run) > 1:
                start = max(0, run[0].start_pos - shift)
                end = max(start, run[-1].end_pos - shift)
                yield span_from_bytes(file, data, start, end), run
            run = [token] if token is not None else []


def _designator_runs(file: str, data: bytes, shift: int, tree,
                     sink: Diagnostics) -> None:
    """Designators that touch, under a pragma that requires a separator
    between them (AMB-146 #1), which 0.1 and 0.2 accept as two
    designators. One RHO1018 per run, with both readings as needs-review
    fix-its: the run split by spaces, and the run quoted as one designator
    (unless it holds a quote already, which no quoted designator can)."""
    for span, run in _runs(file, data, shift, tree):
        text = "".join(str(part) for part in run)
        fixits = [FixIt(
            f"read it as {len(run)} designators",
            "needs-review",
            (Edit(span, " ".join(str(part) for part in run)),),
        )]
        if '"' not in text:
            fixits.append(FixIt(
                f"read it as the one designator `{text}`",
                "needs-review",
                (Edit(span, f'"{text}"'),),
            ))
        sink.add("RHO1018", {"text": text}, primary=span,
                 fixits=tuple(fixits))


def _names_in(tree, words):
    """Each FREE_NAME of `tree` that is one of `words` and a name: a bound
    name or a reference to one. A pin a rule or a side names is not a
    bound name (spec 02, Names), so it is not one."""
    work = [tree]
    while work:
        node = work.pop()
        children = getattr(node, "children", None)
        if children is None:
            continue
        names = [child for child in children
                 if getattr(child, "type", None) == "FREE_NAME"]
        if node.data in _PIN_REFERENCES:
            # A side's own name is bound; its pins, and a rule's, are not.
            names = names[:1] if node.data == "side_decl" else []
        yield from (token for token in names if str(token) in words)
        work.extend(child for child in children if hasattr(child, "data"))


def _reserved_names(file: str, data: bytes, shift: int, tree,
                    loaded: _Loaded, sink: Diagnostics,
                    version: str) -> None:
    """From the version that reserves it on, a word of RESERVED_SINCE is no
    name (RHO1019): not a bound name, and not a reference to one, which
    could never resolve. Earlier versions bind it freely, which is what
    makes reserving it additive."""
    key = _version_key(version)
    reserved = {word: since for word, since in loaded.reserved_since.items()
                if _version_key(since) <= key}
    if not reserved:
        return
    for token in _names_in(tree, reserved):
        sink.add("RHO1019", {"word": str(token),
                             "version": reserved[str(token)]},
                 primary=_token_span(file, data, shift, token))


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
