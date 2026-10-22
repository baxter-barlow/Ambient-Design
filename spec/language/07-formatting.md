# 07 — Formatting and the canonical form

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

Every Rhoform source has exactly one canonical spelling (I1). This
section defines it: the bytes `rhoform fmt` writes for a source that
parses clean. There are no options; a conforming formatter given the
same source MUST produce the same bytes. The reference implementation is
`rhoform/fmt.py`, and the formatter cases under
[`spec/conformance/fmt/`](../conformance/fmt/) pin the canonical form
byte for byte: each case's input MUST format to its expected file, and
each expected file MUST format to itself. The self-check and the
normalized AST below are properties of the formatter rather than of
its output, and are tested by the reference implementation's own
suite (`rhoform/tests/test_fmt.py`).

Formatting never changes what a design means. It re-spaces, re-indents,
re-orders what carries no order, rewrites quantity literals to their
normal form ([03 — Literals](03-literals.md)), and re-places comments
by the attachment rules below. Every other token is written exactly as
the author wrote it.

## Refusal and the self-check

A formatter MUST format only a source that parses clean: a complete
parse tree and no error-severity diagnostic. Any other source is
refused: the formatter returns the parse's diagnostics and no bytes. A
recovered tree is the file with its broken statements removed, so
formatting one would delete the author's broken lines.

Before it returns bytes, the formatter MUST verify four properties of
its own output:

1. the output parses clean;
2. the output's normalized AST (below) equals the input's;
3. formatting the output again changes nothing;
4. the output carries exactly the input's comments, counted as a
   multiset of comment texts.

A failure of any of the four is an internal error of the formatter
(the CLI's exit `2`). The output is never returned or written.

## Layout

- Indentation is exactly four spaces per block level.
- The file opens with its header comments (see Comments), then the
  pragma line, then exactly one blank line.
- Modules appear in source order, each preceded by exactly one blank
  line. Modules are never sorted.
- No blank line follows a block header, and none precedes the end of a
  block. Inside a module body, blank lines exist only between runs
  (see Ordering), exactly one per boundary. Every other blank line is
  removed, wherever it was and however many there were.
- No line carries trailing spaces, and the file ends with exactly one
  line feed (one is added when the source had none).

## The canonical shape of each statement

One space separates words. `=` and `~` have one space on each side;
list separators are `, `. No space precedes the `(` of an argument
list, a net's attribute list, or an assertion's subject; one space
precedes a table's column list. A statement with a block ends its
header line with `:`. Argument lists, attribute lists and column lists
never wrap: a header the author wrapped over several lines is written
on one line.

| Statement | Canonical shape | Order of its lists |
|---|---|---|
| module | `module Power:` | (its body: see Ordering) |
| port | `port vin power_in` | |
| instance | `r1 = new rhoform.lib.passive.Resistor(power_rating = 250mW, resistance = 1kohm)` | arguments sorted by name |
| pin | `pin a passive 1 2 A1` | designators sorted |
| part | `part abstract` or `part "key"`, with a `:` and one constraint per line when it has any | constraints sorted by name |
| constraint | `package = "0402"` | |
| hardware | `hardware test_point` | |
| flag | `dnp`, `exclude_from_bom`, `no exclude_from_bom`, `board_only`, `no board_only` | |
| net | `net VCC(ground_domain = "GND", voltage_domain = "5V"):` with one member per line | attributes sorted by name; members sorted |
| isolated | `isolated tp1.a` | |
| chain | `r1.b ~ d1.a ~ vout` | endpoints keep source order |
| table | `table rhoform.lib.passive.Resistor part abstract (resistance, part.package):` with one row per line | columns keep source order; rows sorted by row name |
| assertion | `assert f static frequency(OUT) within 1kHz to 2kHz` | |

An empty argument list and an empty attribute list are removed:
`new L()` is written `new L`, and `net N():` is written `net N:`. A
table keeps `()`, which its grammar requires.

Chain endpoints are never reordered: the head of a chain is a
binding-checked position ([02 — Grammar](02-grammar.md#names)), so
moving a non-binding endpoint into it could produce a file the parser
rejects. Table columns are never reordered: a row whose arity is wrong
is a checker error, not a parse error, and reordering columns would
silently move its cells.

Table rows are written as an aligned grid: the row name, then each
value, every column padded with spaces to the width of its widest cell
(row names counting as the first column), cells separated by two
spaces, and the padding of the last cell removed. A row with fewer
cells than another pads only the columns it has.

## Literals

Every quantity literal — a value, a constraint, a table cell, an
assertion bound — is rewritten to its normal form as
[03 — Literals](03-literals.md) defines it (`4700pF` becomes `4.7nF`,
`2.0V +/- 10.0%` becomes `2V +/- 10%`). NUMBER and INTEGER tokens,
strings, names, `true` and `false` are written exactly as authored:
the normal form is defined for quantities only, so `0.50` in a
dimensionless bound stays `0.50`.

## Ordering

### Collation (F-2)

Every sort in this section uses one collation, natural sort. A string
is split into maximal runs of ASCII digits and maximal runs of
non-digits, and two strings compare run by run, left to right:

- two digit runs compare by numeric value, and equal values by run
  length, shorter first (`1` before `01`);
- two non-digit runs compare bytewise as whole runs, so a run that is a
  prefix of the other sorts first;
- a digit run and a non-digit run compare by their first bytes;
- when every run compared is equal, the string with fewer runs sorts
  first.

Natural sort puts `c2` before `c10`. It differs from bytewise order
in one more way worth stating, because both orders are plausible: in
`r1.a` against `r.a` the first runs are `r` and `r.a`, and `r` is a
prefix of `r.a`, so `r1.a` sorts first. The conformance gate checks
that this sample is in natural order:

```text
R2 _x a1 a.b c c1 c1a c2 c10 c010 r1.a r.a
```

Every sort is stable: two entries with equal keys (a duplicate name,
which the elaborator reports) keep their source order.

### Paragraph sort in a module body (F-1)

A module body is divided into **runs**. A new run starts at the body's
first statement, at a statement separated from the previous statement
by a blank line, and at a statement that has own-line comments of its
own (including comments hoisted out of its wrapped header; see
Comments). Statements are sorted only within their run, by rank, then
by name under the collation above, then by source position; runs keep
their source order. Sorting never moves a statement across a blank line
or past a comment, so an author's grouping survives and a section
comment keeps labelling its section.

### Statement ranks (F-1)

The rank of each statement kind, by its production in
[`rhoform.ebnf`](../../lang/grammar/rhoform.ebnf). The conformance gate
reconciles this table against the reference implementation.

| Rank | Production | Example | Within the rank, ordered by |
|---|---|---|---|
| 0 | `port_decl` | `port vin power_in` | port name |
| 1 | `table_decl` | `table T (v):` | the least of its row names |
| 2 | `instance_decl` | `r1 = new L` | instance name |
| 3 | `net_decl` | `net VCC:` | net name |
| 4 | `isolated_decl` | `isolated tp1.a` | source position |
| 4 | `chain` | `a ~ b` | source position |
| 5 | `assertion` | `assert f static frequency(OUT) at least 1Hz` | assertion name |

Chains and `isolated` statements share rank 4 and are never reordered
among themselves.

### Instance body order (F-5)

An instance body is always sorted, by the word its line opens with,
in this order. The conformance gate reconciles this table against the
reference implementation.

| Rank | Opening word | Notes |
|---|---|---|
| 0 | `pin` | pins ordered by pin name |
| 1 | `part` | |
| 2 | `hardware` | |
| 3 | `exclude_from_bom` | or its negated form |
| 4 | `board_only` | or its negated form |
| 5 | `dnp` | |

### Other sorted blocks

A part's constraints, a net's members and a table's rows are always
sorted, never divided into runs: constraints by name, members by their
full endpoint text (`r1.a`), rows by row name.

## Comments

Comments are not part of the parse tree, so the formatter recovers
them from the source text: the first `#` on a line that is outside a
string literal starts a comment, and the pragma line carries none. A
comment's text is kept exactly, from its `#` to the end of the line,
except that trailing spaces are removed. Each comment attaches to
exactly one place, and is written there:

- **Header comments** are the comments before the pragma. They are
  written first, at column 0, in source order. A run of blank lines
  between two of them becomes one blank line, blank lines before the
  first are removed, and one blank line separates the last from the
  pragma when the source had at least one there.
- **Trailing comments** share the last physical line of a statement's
  header. They are written after the canonical line, separated from it
  by two spaces; on a table row, after the padded row.
- **Hoisted comments** sit on any other physical line of a header the
  author wrapped inside parentheses. Because argument lists never wrap,
  they have no place inside the header: they are written as own-line
  comments directly above the statement, in source order (F-6).
- **Own-line comments** stand on a line of their own after the pragma.
  Let the next statement be the first statement, at any depth, that
  starts after the comment, and the closed blocks be the blocks that
  contain the previous statement but not the next one (the file itself
  is never one). When the comment's column is greater than the next
  statement's column (0 when there is none) and some block closed, the
  comment is a **block trailer**: it trails the innermost closed block
  whose statements' source column is no greater than the comment's
  column, or the outermost closed block when none qualifies, and it is
  written after that block's last line at the block's indentation.
  Otherwise the comment **leads** the next statement and is written
  directly above it at its indentation. With no next statement, it is
  a **file trailer**.
- **File trailers** are written after the last module, following one
  blank line, at column 0, in source order.

A leading comment of a statement in a module body opens a run (see
Ordering) and stays at the top of that run while the run's statements
sort beneath it. When such a run is not the body's first, one blank
line precedes its comments, whether or not the source had one there.
In every other block a leading comment moves with its statement
wherever sorting puts it.

When two trailers of different blocks close at the same point, each is
written with its own block, so an outer block's trailer that preceded
an inner block's trailer in the source follows it in the output.

## The normalized AST (AC6)

AC6 requires that two sources with identical post-normalization ASTs
format to byte-identical output. Because comments are not in the parse
tree, a literal reading would require the formatter to delete them;
the AST AC6 means is therefore defined here, and the formatter's
self-check compares it.

The **normalized AST** of a clean source is:

- its header comments, with the blank-line break before each and
  whether a blank line precedes the pragma;
- the pragma;
- its modules in source order, each one a node.

A node is a statement's parse tree with every quantity token replaced
by its normal form, its argument and attribute lists sorted by name
(an empty list is absent), and its designators sorted; plus its
leading and trailing comments; plus, when it has a block, that block.
A block is its sequence of runs (one run, except in a module body),
each run being its comments and its nodes in canonical order, plus the
block's trailer comments.

The normalized AST erases exactly what the canonical form does not
keep: indentation width, spacing within a line, wrapping inside
parentheses, blank lines that do not divide runs, the order of
statements within a run and of every sorted list, quantity spellings,
the column of a comment within its attachment, trailing spaces after a
comment, and whether the file ended with a line feed. Two sources with
equal normalized ASTs MUST format to the same bytes, and formatting
MUST preserve the normalized AST.
