# 01 — Lexical structure

*Rhoform Language Specification · normative, v0.2 · CC-BY-4.0 (see
[spec/README.md](../README.md))*

## Bytes

A Rhoform source file is a sequence of bytes. Every byte MUST be
printable ASCII (0x20–0x7E) or LF (0x0A). In particular:

- A **tab** (0x09) is an error anywhere, including inside a comment: two
  files that differ by a tab must not be the same program, and a layout
  language in which a tab silently equals some number of spaces has two
  spellings for one indentation.
- A **carriage return** (0x0D) is an error: sources use LF line endings
  only.
- Any other **control character** (NUL, VT, FF, DEL, ...) is an error;
  it is reported as a control character, not as "non-ASCII", because DEL
  is ASCII and a diagnostic must not say otherwise.
- Any **non-ASCII** byte sequence is an error. The ASCII spellings exist
  for every symbol the language needs (`+/-` for ±, `u` for µ, `ohm` for
  Ω, `degC` for °C).

A reader MUST synthesize a final line terminator when the file's last
byte is not LF. This is a property of the reader, not of the language:
every statement is newline-terminated in the token stream, and a file is
not rejected over its last byte.

## Layout

Blocks are expressed by indentation, resolved by the reader into INDENT
and DEDENT tokens so the grammar itself is context-free over the token
stream (L5). Indentation is spaces only (the tab rule above). A line's
indentation MUST return to an enclosing block's level when it decreases;
an indentation matching no open level is an error.

Blank lines and comment-only lines carry no layout: they neither open
nor close a block, wherever they appear.

Inside parentheses `(` `)`, line breaks and indentation are not layout —
a parameter list may wrap. Parentheses MUST balance by end of file.

Square brackets `[` `]` (syntax 0.2: array sizes and indexes) do NOT
suspend layout. An array size or an index never wraps, so a line break
inside one is an ordinary syntax error on that line, and an unclosed `[`
cannot join the lines after it into one logical line the way an
unclosed `(` would.

## Punctuation

The comparison operators belong to an `if` condition and the offset
operators to an index (`c[i + 1]`). A two-character operator is one
token: `<=` is never `<` followed by `=`. A `-` that begins a numeral
is that number's sign, and the `+/-` of a toleranced quantity belongs
to the quantity literal ([03 — Literals](03-literals.md)); neither is
punctuation in the sense of the list below.

### Punctuation tokens

Every punctuation token of the grammar, outside literals and comments.
This list is reconciled against the grammar source of truth by the
conformance gate. Syntax 0.2 added the square brackets, the six
comparison operators and the two offset operators.

`(` `)` `,` `.` `:` `=` `~` `[` `]` `==` `!=` `<` `<=` `>` `>=` `+` `-`

## Comments

A comment starts at `#` and runs to end of line. The exception is the
pragma word: a `#` immediately followed by the word `pragma` begins the
syntax-version pragma, not a comment. The exclusion ends at a word
boundary, so `#pragmatic` is an ordinary comment.

## The syntax-version pragma

The first statement of every file MUST be exactly one of these lines,
one per syntax version this specification defines:

```text
#pragma rhoform-syntax 0.1
#pragma rhoform-syntax 0.2
#pragma rhoform-syntax 0.3
```

Blank lines and comments may precede it. The version is `major.minor`
with no patch component: the pragma gates syntax, and a patch level
would imply a syntax difference that cannot exist. A reader MUST reject
a file whose pragma names a version it does not implement; a version
header nothing validates cannot do its one job.

### Syntax versions

An implementation of this specification implements the version set
{0.1, 0.2, 0.3}, and MUST accept a file declaring any of them.
Syntax 0.2 is the current version: a new file SHOULD declare it, and a
fix-it that writes a pragma writes the current version.

Of these, the unfrozen version set {0.3} may still change. An unfrozen
version is a working version (decision OD8): its constructs, their
diagnostics and the IR version that carries them may change in place
until it is frozen, so a file declaring it is not yet promised to keep
its meaning. It is never the current version, a toolchain does not
announce it as a language version a package may require
([08 — Packages](08-packages.md)), and no tagged release may ship while
any syntax or IR version is unfrozen. Syntax 0.3 is frozen with the M2
exit.

**Deviation from L8, recorded 2026-10-24.** L8 gates unstable syntax
behind `#pragma experiment(...)`. Syntax 0.3 is instead opened as an
unfrozen version, because the M2 checkers that give its statements
their meaning land one at a time, and an experiment mechanism does not
exist to gate them behind. The no-release rule above is the
compensating control: nothing unfrozen reaches a user as a stable
version.

0.2 is a strict superset of 0.1. Every valid 0.1 file is a valid 0.2
file with the same parse tree and the same meaning, so raising a file's
pragma from 0.1 to 0.2 never changes what it says. That is what makes
the change additive, and why E1 requires no migrator for it. One change
of meaning is deliberate and is not a syntax change: a toolchain that
implements this version set resolves the standard library's reserved
prefix `rhoform.lib.` against its bundled library in a 0.1 file too, so
a 0.1 file that names something under the prefix can mean something
different from what a toolchain without the library made of it, or be
refused ([04 — Elaboration](04-elaboration.md) records the departure
from S-1). The pragma still changes nothing there. What 0.2
adds is listed in
[02 — Grammar](02-grammar.md#syntax-02-additions); every word it
promoted to a keyword was reserved in 0.1, so no 0.1 file could bind
one.

0.3 is likewise a superset of 0.2 for every file that declares 0.2 or
earlier: such a file that is valid parses to the same tree and means the
same thing under an implementation of 0.3, and one that is not draws the
diagnostics 0.2 gave it, except that a construct only 0.3 has draws
`RHO1016` (below) where 0.2 had an error at its first token. Its new
statements open with soft keywords, words 0.2 never reserved, so a 0.2
file may still bind `supply`, `draw`, `waive`, `rule`, `side`, `warning`
or `variant` as a name, and a line such a word heads is read as 0.2 read
it unless the file parses only as 0.3 statements. A file declaring 0.3
may not bind the words 0.3 reserves (`RHO1019`), and it reads a run of
designators with no separator, `01`, as the error `RHO1018` where 0.1
and 0.2 read two designators. Raising a file's pragma to 0.3 therefore
does not only add, which the fix-it below accounts for. What 0.3 adds is
listed in [02 — Grammar](02-grammar.md#syntax-03-additions-unfrozen).

One grammar defines every version, and the version is checked after
parsing. A construct newer than the file's pragma is the syntax error
`RHO1016` (`syntax-needs-newer-pragma`). It is reported once per file
however many such constructs the file holds: its `required` param is the
highest version any of them needs, the primary span is the first
construct in source order that needs that version, the `count` param
says how many constructs newer than the pragma there are, and its one
fix-it rewrites the version in the pragma to `required`. That fix-it is
machine-applicable when `required` only adds to the file. When
`required` refuses a designator run the file holds (`RHO1018`), the
fix-it also spaces each run out (`01` to `0 1`), which is how the
declared version reads it, and stays machine-applicable. When `required`
reserves a word the file binds as a name (`RHO1019`), no edit can choose
the new name: the fix-it is needs-review, and its message names the
words to rename. A missing pragma, or one naming a version outside
the set, is `RHO1005` (`missing-or-wrong-pragma`) instead; its fix-it
writes the current version, and the rest of such a file is checked as
the current version.

The expected-token lists of `RHO1006` and `RHO1007` come from the one
grammar, filtered by the file's pragma: a token only a newer version
allows is left out, so a 0.1 file is never told to write `import` and a
0.2 file never `supply` (AMB-146 #2). When the filter would leave
nothing, the parse already stands inside a newer construct, and the list
is given whole.

Unstable syntax, when it exists, gates behind `#pragma experiment(...)`
(L8). No version defines experiments: the 0.2 additions are stable
syntax, and 0.3's are unfrozen until M2 exits (above).

## Frozen asymmetries (v0.1)

Two lexical-level asymmetries were frozen deliberately with the syntax
(they reproduce the winning bake-off prototype's behavior, and changing
them during the freeze would have changed the language away from the one
that was measured). They are normative in v0.1 and carry into 0.2
unchanged; regularising either is a breaking syntax change subject to
the E1 auto-migrator policy.

1. **The pragma is recognized by the comment exclusion, not by line
   position.** Consequently a mid-line `#pragma x` after code is an
   error (it is not a trailing comment), while `#pragmatic` on its own
   line is a comment. Both directions are pinned by conformance cases.
2. **Reserved-word checking is positional** — see
   [02 — Grammar](02-grammar.md#names): a keyword cannot be *bound* as a
   name, but may appear in non-binding name positions.
