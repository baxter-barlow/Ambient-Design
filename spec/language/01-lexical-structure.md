# 01 — Lexical structure

*Rhoform Language Specification · normative, v0.1 · CC-BY-4.0 (see
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

Inside parentheses `(` `)` and square brackets `[` `]`, line breaks and
indentation are not layout — a parameter list may wrap. Brackets MUST
balance by end of file.

## Comments

A comment starts at `#` and runs to end of line. The exception is the
pragma word: a `#` immediately followed by the word `pragma` begins the
syntax-version pragma, not a comment. The exclusion ends at a word
boundary, so `#pragmatic` is an ordinary comment.

## The syntax-version pragma

The first statement of every file MUST be exactly:

```text
#pragma rhoform-syntax 0.1
```

Blank lines and comments may precede it. The version is `major.minor`
with no patch component: the pragma gates syntax, and a patch level
would imply a syntax difference that cannot exist. A reader MUST reject
a file whose pragma names a version it does not implement; a version
header nothing validates cannot do its one job.

Unstable syntax, when it exists, gates behind `#pragma experiment(...)`
(L8); v0.1 defines no experiments.

## Frozen asymmetries (v0.1)

Two lexical-level asymmetries were frozen deliberately with the syntax
(they reproduce the winning bake-off prototype's behavior, and changing
them during the freeze would have changed the language away from the one
that was measured). They are normative in v0.1; regularising either is a
breaking syntax change subject to the E1 auto-migrator policy.

1. **The pragma is recognized by the comment exclusion, not by line
   position.** Consequently a mid-line `#pragma x` after code is an
   error (it is not a trailing comment), while `#pragmatic` on its own
   line is a comment. Both directions are pinned by conformance cases.
2. **Reserved-word checking is positional** — see
   [02 — Grammar](02-grammar.md#names): a keyword cannot be *bound* as a
   name, but may appear in non-binding name positions.
