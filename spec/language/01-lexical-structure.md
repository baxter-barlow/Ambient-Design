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
```

Blank lines and comments may precede it. The version is `major.minor`
with no patch component: the pragma gates syntax, and a patch level
would imply a syntax difference that cannot exist. A reader MUST reject
a file whose pragma names a version it does not implement; a version
header nothing validates cannot do its one job.

### Syntax versions

An implementation of this specification implements the version set
{0.1, 0.2}, and MUST accept a file declaring either. Syntax 0.2 is the
current version: a new file SHOULD declare it, and a fix-it that writes
a pragma writes the current version.

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

One grammar defines both versions, and the version is checked after
parsing. A construct only 0.2 has, in a file whose pragma declares 0.1,
is the syntax error `RHO1016` (`syntax-needs-newer-pragma`). It is
reported once per file however many such constructs the file holds: the
primary span is the first of them in source order, the `count` param
says how many there are, and its one fix-it is machine-applicable and
rewrites only the version in the pragma, from 0.1 to 0.2. A missing
pragma, or one naming a version outside the set, is `RHO1005`
(`missing-or-wrong-pragma`) instead; its fix-it writes the current
version, and the rest of such a file is checked as the current version.

The expected-token lists of `RHO1006` and `RHO1007` come from the one
grammar, so under a 0.1 pragma they may name a token only 0.2 allows.
Following such a hint is safe: it draws `RHO1016`, whose fix-it
completes the repair.

Unstable syntax, when it exists, gates behind `#pragma experiment(...)`
(L8). Neither 0.1 nor 0.2 defines experiments: the 0.2 additions are
stable syntax.

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
