"""The canonical formatter (R16/I1): one spelling for every parse tree.

ZERO OPTIONS. There is no configuration: two sources that mean the same
thing, carry the same comments and break into the same paragraphs format to
the same bytes (AC6). The rules are the decision record's F-1..F-12, and the
spacing and per-construct layout match the bake-off renderer that I1 names
as the formatter's prototype, so its measured renderings stay fixed points
(modulo T3 normalization and natural sort).

REFUSAL. Only a clean parse is formatted (`ParseResult.ok`). A recovered
tree is "the file with its broken statements removed", and formatting it
would delete the author's broken lines; a refused file returns the parse
diagnostics and no bytes.

COMMENTS ARE NOT IN THE TREE. The grammar's `_NEWLINE` swallows comment
lines and the Indenter drops newline runs inside parentheses, so comments
are recovered from the source text by a string-aware line scanner: the
first `#` outside a `"..."` string on a physical line starts a comment
(the pragma line excepted). That is sound only because the formatter runs
on clean parses, where no string is unterminated. The same scanner tracks
parenthesis depth, which yields LOGICAL lines (a wrapped argument list is
one logical line), and every statement header is exactly one logical line.
Statement extents therefore come from tokens and logical lines, never from
`meta.end_pos`, which includes the swallowed newline run.

ATTACHMENT (F-10), in one place, `_attach_comments`:
  - before the pragma: header comments, kept in order at column 0;
  - on the last physical line of a statement header: a trailing comment,
    re-emitted after two spaces;
  - inside a wrapped header (between its first and last physical line):
    hoisted to an own-line comment above the statement (F-6);
  - on a line of its own: a leading comment of the next statement, at that
    statement's indent - unless it is indented deeper than that statement,
    in which case it trails the innermost block that closed in between
    whose indent it reaches (the outermost such block when it reaches
    none), emitted at that block's indent after its last line;
  - after the last statement at column 0: a file trailer.

DISPATCH PER PRODUCTION. Every grammar production a statement can be is a
row in three tables: how its header renders (`_HEADS`), which child
subtrees form its block and how that block orders (`_BLOCKS`), and its sort
key (`_KEYS`). Growing the grammar (the 0.2 surface: imports, component
definitions, parameter lists, `if`/`for`, arrays) adds rows rather than
rewriting the walk.

THE SELF-CHECK (F-11). Before bytes are returned: the output re-parses
clean, its normalized AST (F-12) equals the input's, formatting it again is
a fixed point, and the multiset of comment texts is unchanged. The AST is
built by a generic walk over the parse tree, independent of the header
renderers, so a renderer that dropped or altered a token is caught rather
than agreeing with itself. A failed self-check raises FormatterError: an
internal error (the CLI's exit 2), never written.
"""

import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field

from .diagnostics import Diagnostics
from .parser import parse
from .quantities import normal_form

INDENT = "    "

_QUANTITY_TYPES = frozenset({"QUANTITY", "QUANTITY_INTERVAL", "QUANTITY_PLAIN"})


class FormatterError(RuntimeError):
    """The formatter's own output failed its self-check. An internal error:
    the bytes are never returned or written."""


@dataclass
class FormatResult:
    """`text` is the canonical source, or None when the input did not parse
    clean; `diagnostics` is the parse's sink either way."""

    text: str | None
    diagnostics: Diagnostics

    @property
    def ok(self) -> bool:
        return self.text is not None


# --------------------------------------------------------------------------
# Collation (F-2)
# --------------------------------------------------------------------------

_RUNS = re.compile(r"[0-9]+|[^0-9]+")


def natural_key(text: str) -> tuple:
    """Natural sort: digit runs compare numerically, then by run length
    (shorter first), and everything else bytewise; the whole string breaks
    any remaining tie bytewise. `c2 < c10`.

    Each run's key leads with its first byte, so a digit run and a text run
    at the same position order exactly as their first bytes would (`.` <
    digits < upper case < `_` < lower case), and the second element (0 for
    digits, 1 for text) is only ever compared between runs of the same
    type. Two text runs compare as whole strings, so a run that is a prefix
    of the other sorts first: `r1.a` (runs `r`, `1`, `.a`) sorts before
    `r.a` (one run), where bytewise order would put `r.a` first."""
    runs = []
    for run in _RUNS.findall(text):
        if run[0].isdigit():
            runs.append((0x30, 0, int(run), len(run)))
        else:
            runs.append((ord(run[0]), 1, run))
    return (tuple(runs), text)


# --------------------------------------------------------------------------
# Tree helpers
# --------------------------------------------------------------------------


def _is_tree(node) -> bool:
    return hasattr(node, "data")


def _tokens(node):
    """Every token under `node`, in source order."""
    if not _is_tree(node):
        yield node
        return
    for child in node.children:
        yield from _tokens(child)


def _first_token(node):
    return next(_tokens(node))


def _subtrees(node, data: str) -> list:
    return [c for c in node.children if _is_tree(c) and c.data == data]


def _subtree(node, data: str):
    found = _subtrees(node, data)
    return found[0] if found else None


def _direct_tokens(node) -> list:
    return [c for c in node.children if not _is_tree(c)]


def _text(token) -> str:
    """A token's canonical spelling: quantities in T3 normal form (F-8),
    every other token verbatim."""
    if token.type in _QUANTITY_TYPES:
        return normal_form(str(token))
    return str(token)


def _dotted(node) -> str:
    """`endpoint`, `chain_head`, `qualified_name`, `column`: names joined
    by dots."""
    return ".".join(str(t) for t in _tokens(node))


def _unwrap(node):
    """`statement` and `instance_stmt` are one-child wrappers."""
    while _is_tree(node) and node.data in ("statement", "instance_stmt"):
        node = node.children[0]
    return node


# --------------------------------------------------------------------------
# Header renderers, one per production (F-5, F-7, F-8)
# --------------------------------------------------------------------------


def _value(node) -> str:
    return _text(node.children[0])


def _arguments(node) -> str:
    args = _subtree(node, "arguments")
    if args is None or not args.children:
        return ""  # F-7: `new L()` and `new L` are one form
    pairs = sorted(
        ((str(a.children[0]), _value(a.children[1])) for a in args.children),
        key=lambda pair: natural_key(pair[0]),
    )
    return "(" + ", ".join(f"{n} = {v}" for n, v in pairs) + ")"


def _head_module(node) -> str:
    return f"module {node.children[1]}"


def _head_port(node) -> str:
    _, name, role = node.children
    return f"port {name} {role}"


def _head_isolated(node) -> str:
    return f"isolated {_dotted(node.children[1])}"


def _head_net(node) -> str:
    head = f"net {node.children[1]}"
    attrs = _subtree(node, "net_attributes")
    if attrs is not None and attrs.children:
        pairs = sorted(
            ((str(a.children[0]), str(a.children[1])) for a in attrs.children),
            key=lambda pair: natural_key(pair[0]),
        )
        head += "(" + ", ".join(f"{n} = {v}" for n, v in pairs) + ")"
    return head


def _head_chain(node) -> str:
    # F-4: chain endpoints keep source order.
    return " ~ ".join(_dotted(child) for child in node.children)


def _head_instance(node) -> str:
    name = node.children[0]
    definition = _dotted(_subtree(node, "qualified_name"))
    return f"{name} = new {definition}{_arguments(node)}"


def _head_pin(node) -> str:
    _, name, role = _direct_tokens(node)
    designators = sorted(
        (str(d.children[0]) for d in _subtrees(node, "designator")),
        key=natural_key,
    )
    return " ".join([f"pin {name} {role}", *designators])


def _head_part(node) -> str:
    return f"part {_direct_tokens(node)[1]}"


def _head_hardware(node) -> str:
    return f"hardware {node.children[1]}"


def _head_negated(node) -> str:
    return f"no {node.children[1]}"


def _head_flag(node) -> str:
    return str(node.children[0])


def _head_constraint(node) -> str:
    return f"{node.children[0]} = {_value(node.children[1])}"


def _head_endpoint(node) -> str:
    return _dotted(node)


def _head_table(node) -> str:
    head = f"table {_dotted(_subtree(node, 'qualified_name'))}"
    binding = _subtree(node, "table_binding")
    if binding is not None:
        head += " part " + str(binding.children[1])
    columns = _subtree(node, "column_list")
    names = [] if columns is None else [_dotted(c) for c in columns.children]
    # F-3: columns keep author order. F-7: a table keeps its `()`.
    return f"{head} ({', '.join(names)})"


def _row_cells(node) -> list[str]:
    return [str(node.children[0])] + [_value(v) for v in node.children[1:]]


def _head_table_row(node) -> str:
    return " ".join(_row_cells(node))


def _head_assertion(node) -> str:
    keyword, name, tier, kind, subject, bound = node.children
    bound_text = " ".join(_text(t) for t in _tokens(bound))
    return f"assert {name} {tier} {kind}({subject}) {bound_text}"


_HEADS = {
    "module_def": _head_module,
    "port_decl": _head_port,
    "isolated_decl": _head_isolated,
    "net_decl": _head_net,
    "chain": _head_chain,
    "instance_decl": _head_instance,
    "pin_decl": _head_pin,
    "part_decl": _head_part,
    "hardware_decl": _head_hardware,
    "negated_flag": _head_negated,
    "flag": _head_flag,
    "constraint": _head_constraint,
    "endpoint": _head_endpoint,
    "table_decl": _head_table,
    "table_row": _head_table_row,
    "assertion": _head_assertion,
}


# --------------------------------------------------------------------------
# Blocks and sort keys (F-1, F-3, F-5)
# --------------------------------------------------------------------------

# production -> (ordering mode, data name of the direct child that holds
# the block). "paragraph": sorted only inside runs delimited by a blank
# line or an own-line comment (F-1). "sorted": always sorted (F-3, F-5).
# "table": always sorted, rendered as an aligned grid.
_BLOCKS = {
    "module_def": ("paragraph", "statement"),
    "instance_decl": ("sorted", "instance_body"),
    "part_decl": ("sorted", "constraint"),
    "net_decl": ("sorted", "endpoint"),
    "table_decl": ("table", "table_row"),
}


def _block_children(node) -> list:
    spec = _BLOCKS.get(node.data)
    if spec is None:
        return []
    _, child = spec
    found = _subtrees(node, child)
    if node.data == "instance_decl":
        found = found[0].children if found else []
    return [_unwrap(c) for c in found]


def _name_key(token) -> tuple:
    return natural_key(str(token))


# F-1: a module body's kind ranks, by grammar production. Chains and
# `isolated` share rank 4 and keep source order. Spec 07 restates this
# table and the conformance gate reconciles the two.
STATEMENT_RANKS = {
    "port_decl": 0,
    "table_decl": 1,
    "instance_decl": 2,
    "net_decl": 3,
    "isolated_decl": 4,
    "chain": 4,
    "assertion": 5,
}

# F-5: an instance body's fixed order, by the word that opens the line
# (`no exclude_from_bom` ranks with `exclude_from_bom`). Restated in spec
# 07 and reconciled the same way.
BODY_RANKS = {
    "pin": 0,
    "part": 1,
    "hardware": 2,
    "exclude_from_bom": 3,
    "board_only": 4,
    "dnp": 5,
}


def _key_table(node) -> tuple:
    rows = [natural_key(str(r.children[0])) for r in _subtrees(node, "table_row")]
    return (STATEMENT_RANKS["table_decl"], min(rows))


def _ranked(production: str, name=None):
    rank = STATEMENT_RANKS[production]
    if name is None:
        return lambda n: (rank,)
    return lambda n: (rank, _name_key(name(n)))


_KEYS = {
    # module body (F-1), ranks from STATEMENT_RANKS
    "port_decl": _ranked("port_decl", lambda n: n.children[1]),
    "table_decl": _key_table,
    "instance_decl": _ranked("instance_decl", lambda n: n.children[0]),
    "net_decl": _ranked("net_decl", lambda n: n.children[1]),
    "isolated_decl": _ranked("isolated_decl"),
    "chain": _ranked("chain"),
    "assertion": _ranked("assertion", lambda n: n.children[1]),
    # instance body (F-5), ranks from BODY_RANKS
    "pin_decl": lambda n: (BODY_RANKS["pin"], _name_key(_direct_tokens(n)[1])),
    "part_decl": lambda n: (BODY_RANKS["part"],),
    "hardware_decl": lambda n: (BODY_RANKS["hardware"],),
    "flag": lambda n: (BODY_RANKS[str(n.children[0])],),
    "negated_flag": lambda n: (BODY_RANKS[str(n.children[1])],),
    # intra-statement lists (F-3)
    "constraint": lambda n: (0, _name_key(n.children[0])),
    "endpoint": lambda n: (0, natural_key(_dotted(n))),
    "table_row": lambda n: (0, _name_key(n.children[0])),
    # modules keep source order
    "module_def": lambda n: (0,),
}


# --------------------------------------------------------------------------
# The line scanner: comments and logical lines
# --------------------------------------------------------------------------


def _comment_start(line: str) -> int | None:
    """Column of the first `#` outside a string, or None. Strings are
    single-line with no escapes, and on a clean parse none is unterminated."""
    in_string = False
    for column, char in enumerate(line):
        if in_string:
            in_string = char != '"'
        elif char == '"':
            in_string = True
        elif char == "#":
            return column
    return None


def _paren_delta(code: str) -> int:
    depth = 0
    in_string = False
    for char in code:
        if in_string:
            in_string = char != '"'
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
    return depth


@dataclass
class _Line:
    comment: str | None       # comment text, trailing spaces stripped
    column: int               # column of the comment's `#`
    statement: int | None     # first physical line of its logical line


def _scan(lines: list[str], pragma_line: int) -> list[_Line]:
    scanned = []
    depth = 0
    start = None
    for number, line in enumerate(lines):
        if number == pragma_line:
            scanned.append(_Line(None, 0, number))
            continue
        cut = _comment_start(line)
        code = line if cut is None else line[:cut]
        comment = None if cut is None else line[cut:].rstrip(" ")
        has_code = bool(code.strip())
        if depth == 0:
            start = number if has_code else None
        scanned.append(_Line(comment, cut or 0, start))
        if start is not None:
            depth = max(0, depth + _paren_delta(code))
    return scanned


def comments_of(source: str) -> Counter:
    """The multiset of comment texts in a clean source (F-11's comment
    check). The pragma line is the first content line that is not a
    comment."""
    counted = Counter()
    seen_pragma = False
    for line in source.split("\n"):
        stripped = line.strip()
        if not seen_pragma and stripped.startswith("#pragma") and not \
                re.match(r"#pragma[A-Za-z0-9_]", stripped):
            seen_pragma = True
            continue
        cut = _comment_start(line)
        if cut is not None:
            counted[line[cut:].rstrip(" ")] += 1
    return counted


# --------------------------------------------------------------------------
# The document: units (one per statement line) in blocks
# --------------------------------------------------------------------------


@dataclass(eq=False)
class _Block:
    owner: "_Unit | None"
    mode: str
    children: list = field(default_factory=list)
    trailer: list = field(default_factory=list)
    column: int = 0  # the children's SOURCE column


@dataclass(eq=False)
class _Unit:
    node: object
    line: int                 # 0-based physical line of the first token
    column: int               # 0-based source column of the first token
    index: int                # position among its siblings in the source
    parent: _Block
    block: _Block | None = None
    leading: list = field(default_factory=list)   # (line, text)
    trailing: str | None = None
    blank_before: bool = False


@dataclass
class _Document:
    header: list              # (text, blank line before it)
    header_gap: bool          # a blank line between header and pragma
    pragma: str
    root: _Block


def _build(source: str, tree) -> _Document:
    lines = source.split("\n")
    pragma = tree.children[0]
    pragma_line = pragma.line - 1
    scanned = _scan(lines, pragma_line)

    root = _Block(owner=None, mode="file")
    units: list[_Unit] = []

    def add(node, parent: _Block, index: int) -> None:
        token = _first_token(node)
        unit = _Unit(node, token.line - 1, token.column - 1, index, parent)
        parent.children.append(unit)
        units.append(unit)
        children = _block_children(node)
        if children:
            unit.block = _Block(owner=unit, mode=_BLOCKS[node.data][0])
            for position, child in enumerate(children):
                add(child, unit.block, position)
            unit.block.column = unit.block.children[0].column

    for position, module in enumerate(_subtrees(tree, "module_def")):
        add(module, root, position)
    units.sort(key=lambda u: u.line)

    header, gap = [], False
    for number in range(pragma_line):
        entry = scanned[number]
        if entry.comment is None:
            gap = bool(header)
            continue
        header.append((entry.comment, gap))
        gap = False

    _attach_comments(scanned, units, root, pragma_line)
    return _Document(header, gap, str(pragma), root)


def _ancestors(unit: _Unit | None) -> list:
    chain = []
    block = None if unit is None else unit.parent
    while block is not None:
        chain.append(block)
        block = None if block.owner is None else block.owner.parent
    return chain


def _attach_comments(scanned: list, units: list, root: _Block,
                     pragma_line: int) -> None:
    by_line = {unit.line: unit for unit in units}
    starts = [unit.line for unit in units]

    for number in range(pragma_line + 1, len(scanned)):
        entry = scanned[number]
        if entry.comment is None:
            continue
        if entry.statement is not None:
            owner = by_line[entry.statement]
            last = number
            while last + 1 < len(scanned) and \
                    scanned[last + 1].statement == entry.statement:
                last += 1
            if number == last:
                owner.trailing = entry.comment
            else:  # inside a wrapped header: hoisted (F-6)
                owner.leading.append((number, entry.comment))
            continue

        at = bisect_right(starts, number)
        following = units[at] if at < len(units) else None
        preceding = units[at - 1] if at > 0 else None
        target_column = 0 if following is None else following.column
        open_after = set(map(id, _ancestors(following)))
        # The file is not an inner block: a comment past the last module
        # trails that module's blocks, or the file at column 0.
        closed = [b for b in _ancestors(preceding)
                  if id(b) not in open_after and b.owner is not None]
        if entry.column > target_column and closed:
            chosen = closed[-1]
            for block in closed:  # innermost first
                if block.column <= entry.column:
                    chosen = block
                    break
            chosen.trailer.append(entry.comment)
        elif following is None:
            root.trailer.append(entry.comment)
        else:
            following.leading.append((number, entry.comment))

    for unit in units:
        unit.leading.sort()
        number = unit.line - 1
        while number > pragma_line and scanned[number].statement is None:
            if scanned[number].comment is None:
                unit.blank_before = True
                break
            number -= 1


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def _sorted(units: list) -> list:
    return sorted(units, key=lambda u: (_KEYS[u.node.data](u.node), u.index))


def _runs(block: _Block) -> list[tuple[list, list]]:
    """The block's children in canonical order, as (comments, units) runs.

    Only a "paragraph" block has more than one run. Its runs are delimited
    by a blank line or an own-line comment (F-1), and the comments that
    delimit a run belong to the RUN: they stay at its top while its
    statements sort beneath them, which is what keeps a section-header
    comment over its section. Every other block keeps comments on their
    statements, which carry them wherever sorting puts them; a "file" block
    keeps source order (modules are not sorted)."""
    if block.mode == "file":
        return [([], list(block.children))]
    if block.mode != "paragraph":
        return [([], _sorted(block.children))]
    runs: list[tuple[list, list]] = []
    for position, unit in enumerate(block.children):
        if position == 0 or unit.blank_before or unit.leading:
            runs.append(([text for _, text in unit.leading], []))
        runs[-1][1].append(unit)
    return [(comments, _sorted(units)) for comments, units in runs]


# --------------------------------------------------------------------------
# Rendering (F-5, F-9, F-10)
# --------------------------------------------------------------------------


def _with_trailing(line: str, comment: str | None) -> str:
    return line if comment is None else f"{line}  {comment}"


def _render_unit(unit: _Unit, depth: int, out: list, head: str | None = None,
                 leading: bool = True) -> None:
    indent = INDENT * depth
    if leading:
        out.extend(indent + text for _, text in unit.leading)
    if head is None:
        head = _HEADS[unit.node.data](unit.node)
    if unit.block is not None:
        head += ":"
    out.append(_with_trailing(indent + head, unit.trailing))
    if unit.block is not None:
        _render_block(unit.block, depth + 1, out)


def _render_block(block: _Block, depth: int, out: list) -> None:
    runs = _runs(block)
    if block.mode == "table":
        # Cells padded to their column's width, two-space gutters, as the
        # prototype's table_body does (F-5). Ragged rows (an arity error
        # the checker reports) pad by whatever columns they have.
        rows = runs[0][1]
        grid = [_row_cells(unit.node) for unit in rows]
        widths: list[int] = []
        for cells in grid:
            for column, cell in enumerate(cells):
                if column == len(widths):
                    widths.append(0)
                widths[column] = max(widths[column], len(cell))
        for unit, cells in zip(rows, grid):
            line = "  ".join(c.ljust(w) for c, w in zip(cells, widths))
            _render_unit(unit, depth, out, head=line.rstrip())
    else:
        paragraph = block.mode == "paragraph"
        for number, (comments, units) in enumerate(runs):
            if number:
                out.append("")
            out.extend(INDENT * depth + text for text in comments)
            for unit in units:
                _render_unit(unit, depth, out, leading=not paragraph)
    out.extend(INDENT * depth + text for text in block.trailer)


def _render(document: _Document) -> str:
    out: list[str] = []
    for text, gap in document.header:
        if gap and out:
            out.append("")
        out.append(text)
    if document.header and document.header_gap:
        out.append("")
    out.append(document.pragma)
    for module in document.root.children:
        out.append("")
        _render_unit(module, 0, out)
    if document.root.trailer:
        out.append("")
        out.extend(document.root.trailer)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# The normalized AST (F-12) and the self-check (F-11)
# --------------------------------------------------------------------------

# Lists whose order carries no meaning, sorted by their entries' first
# token; F-7's empty `()` is dropped.
_UNORDERED = frozenset({"arguments", "net_attributes"})


def _canon(node, skip: str | None = None):
    """A generic walk: every token (normalized), every subtree, sortable
    lists in canonical order. It does not use the header renderers, so it
    is an independent witness of what the output means."""
    if not _is_tree(node):
        return _text(node)
    children = [c for c in node.children
                if not (skip and _is_tree(c) and c.data == skip)]
    if node.data in _UNORDERED:
        if not children:
            return None
        children = sorted(children,
                          key=lambda c: natural_key(str(c.children[0])))
    if node.data == "pin_decl":
        fixed = [_text(c) for c in children if not _is_tree(c)]
        designators = sorted((str(c.children[0]) for c in children
                              if _is_tree(c)), key=natural_key)
        return ("pin_decl", tuple(fixed), tuple(designators))
    walked = tuple(w for w in (_canon(c) for c in children) if w is not None)
    return (str(node.data), walked)


def _ast_unit(unit: _Unit, leading: bool = True) -> tuple:
    skip = _BLOCKS.get(unit.node.data, (None, None))[1]
    return (
        _canon(unit.node, skip),
        tuple(text for _, text in unit.leading) if leading else (),
        unit.trailing,
        None if unit.block is None else _ast_block(unit.block),
    )


def _ast_block(block: _Block) -> tuple:
    return (
        tuple(
            (tuple(comments),
             tuple(_ast_unit(u, block.mode != "paragraph") for u in units))
            for comments, units in _runs(block)
        ),
        tuple(block.trailer),
    )


def normalized_ast(document: _Document) -> tuple:
    """F-12's AST: the parse tree with quantities normalized, sortable
    lists in canonical order and empty `()` removed, plus the attached
    comments and the paragraph runs. Equal ASTs format to equal bytes."""
    return (tuple(document.header), document.header_gap, document.pragma,
            _ast_block(document.root))


def _format_clean(source: str, tree) -> tuple[str, _Document]:
    document = _build(source, tree)
    return _render(document), document


def format_source(source: str, file: str = "design.rhoform") -> FormatResult:
    """Format one source. Refuses (text None, the parse's diagnostics) unless
    the parse is clean; raises FormatterError when the output fails its
    self-check, and LarkUnavailable when the parser cannot run."""
    sink = Diagnostics()
    parsed = parse(source, file=file, sink=sink)
    if not parsed.ok:
        return FormatResult(text=None, diagnostics=sink)
    text, document = _format_clean(source, parsed.tree)
    _self_check(source, document, text, file)
    return FormatResult(text=text, diagnostics=sink)


def _self_check(source: str, document: _Document, text: str, file: str) -> None:
    again = parse(text, file=file, sink=Diagnostics())
    if not again.ok:
        raise FormatterError(
            f"{file}: the formatted output does not re-parse clean:\n"
            + again.diagnostics.render()
        )
    second, redone = _format_clean(text, again.tree)
    if normalized_ast(redone) != normalized_ast(document):
        raise FormatterError(
            f"{file}: the formatted output's normalized AST differs from "
            "the input's"
        )
    if second != text:
        raise FormatterError(f"{file}: formatting is not idempotent")
    if comments_of(text) != comments_of(source):
        raise FormatterError(
            f"{file}: the formatted output does not carry the input's "
            "comments"
        )


def is_canonical(source: str, file: str = "design.rhoform") -> bool:
    """True when `source` parses clean and is already in canonical form."""
    result = format_source(source, file=file)
    return result.text == source


def first_difference(old: str, new: str) -> int:
    """Index of the first character where two texts differ (the length of
    the shorter when one is a prefix of the other); -1 when equal."""
    if old == new:
        return -1
    for position, (a, b) in enumerate(zip(old, new)):
        if a != b:
            return position
    return min(len(old), len(new))
