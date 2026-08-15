"""The shared layout tokenizer: L5's INDENT/DEDENT stream.

L5 fixes this layer for BOTH candidates — "newline + indentation blocks,
ASCII only, keyword-based, context-free over a layout-tokenized stream" — so
the candidates differ in their grammar over this stream, never in the stream
itself. Sharing the lexer is what makes the comparison a comparison: two
hand-written lexers would differ in error quality and blank-line handling, and
those differences would show up in the results looking like grammar
differences.

Quantities are lexed as ONE token. `100kohm +/- 1%` contains spaces and
parentheses, so splitting it into pieces and reassembling them in each parser
would put the shared literal syntax back into each candidate's grammar, where
it could diverge. The lexer matches the longest quantity at a digit and hands
the parser a single QUANTITY token.

Implicit line joining inside `(` and `[` is Python-shaped (P4) and load
bearing for candidate B, whose parameter lists are the one construct here
that outgrows a line.
"""

import re

from .diagnostics import Diag, ParseFailure, Span
from .quantities import QuantityError, parse_quantity

INDENT_WIDTH = 4

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUM = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
_NUMBER_RE = re.compile(_NUM)
_UNIT = r"[A-Za-z][A-Za-z0-9/]*"
# Same five forms as quantities.py, matched left-anchored at a digit. The
# three optional branches start with distinct literals (` +/- `, ` (`, ` to `)
# so they are mutually exclusive and ordered-alternation cannot truncate a
# longer literal into a shorter one.
_QUANTITY_RE = re.compile(
    rf"{_NUM}{_UNIT}"
    rf"(?: \+/- {_NUM}(?:{_UNIT}|%)"
    rf"| \({_NUM}{_UNIT} to {_NUM}{_UNIT}\)"
    rf"| to {_NUM}{_UNIT})?"
)

_OPERATORS = ("~", "=", ":", ",", ".", "(", ")", "[", "]")


class Token:
    __slots__ = ("kind", "text", "line", "column", "offset")

    def __init__(self, kind: str, text: str, line: int, column: int, offset: int):
        self.kind = kind
        self.text = text
        self.line = line
        self.column = column
        self.offset = offset

    def span(self, length: int | None = None) -> Span:
        return Span(
            line=self.line,
            column=self.column,
            offset=self.offset,
            length=len(self.text) if length is None else length,
        )

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.text!r}, line={self.line})"


def tokenize(source: str) -> list[Token]:
    """Turn source into a layout-tokenized stream, or raise ParseFailure.

    Collects every lexical error before giving up. A lexer that stopped at the
    first bad character would hand the repair loop one problem per iteration,
    which is the convergence failure P2 warns about.
    """
    diagnostics: list[Diag] = []
    tokens: list[Token] = []
    indents = [0]
    bracket_depth = 0
    # Where each still-open bracket was opened. A dropped `)` swallows the
    # rest of the file into one logical line, so reporting at end-of-file
    # blames the last line for the first line's mistake — the single worst
    # thing a layout-language diagnostic can do to a repair loop.
    open_brackets: list[tuple[int, int, int]] = []
    offset = 0
    line_number = 0

    for raw_line in source.split("\n"):
        line_number += 1
        line_start = offset
        offset += len(raw_line) + 1  # +1 for the newline consumed by split

        for index, char in enumerate(raw_line):
            if char == "\t":
                diagnostics.append(
                    Diag(
                        code="AEDX0002",
                        message="tab character; indentation and spacing are spaces only",
                        span=Span(line_number, index + 1, line_start + index),
                        params={"character": "tab"},
                        fixit="replace the tab with spaces",
                    )
                )
            elif not (" " <= char <= "~"):
                diagnostics.append(
                    Diag(
                        code="AEDX0001",
                        message=(
                            f"non-ASCII character U+{ord(char):04X}; the surface "
                            "syntax is ASCII only (L5)"
                        ),
                        span=Span(line_number, index + 1, line_start + index),
                        params={"codepoint": f"U+{ord(char):04X}"},
                        fixit="use the ASCII spelling, e.g. `+/-` for U+00B1",
                    )
                )

        stripped = raw_line.strip()

        if bracket_depth == 0:
            # Blank and comment-only lines carry no layout: they neither open
            # nor close a block. Treating them as dedents is a classic
            # layout-language bug and would make every arm's error messages
            # depend on the author's blank lines.
            if not stripped or stripped.startswith("#"):
                if stripped.startswith("#"):
                    # A `#pragma ...` at the start of a line is L8's syntax-
                    # version marker and reaches the parser; every other `#`
                    # line is a comment and does not. Lexing them alike and
                    # sorting it out in each parser would give the two
                    # candidates two chances to disagree about a construct L8
                    # has already fixed.
                    kind = "PRAGMA" if stripped.startswith("#pragma") else "COMMENT"
                    tokens.append(
                        Token(
                            kind,
                            stripped,
                            line_number,
                            len(raw_line) - len(raw_line.lstrip(" ")) + 1,
                            line_start,
                        )
                    )
                    tokens.append(Token("NEWLINE", "", line_number, 1, line_start))
                continue

            indent = len(raw_line) - len(raw_line.lstrip(" "))
            if indent > indents[-1]:
                indents.append(indent)
                tokens.append(Token("INDENT", " " * indent, line_number, 1, line_start))
            else:
                while indent < indents[-1]:
                    indents.pop()
                    tokens.append(Token("DEDENT", "", line_number, indent + 1, line_start))
                if indent != indents[-1]:
                    diagnostics.append(
                        Diag(
                            code="AEDX0003",
                            message=(
                                f"indentation of {indent} spaces matches no enclosing "
                                f"block (open levels: {indents})"
                            ),
                            span=Span(line_number, 1, line_start, max(indent, 1)),
                            params={"indent": indent, "open_levels": list(indents)},
                            fixit=f"indent to {indents[-1]} spaces",
                        )
                    )
                    indents.append(indent)

        position = len(raw_line) - len(raw_line.lstrip(" "))
        while position < len(raw_line):
            char = raw_line[position]
            here = line_start + position

            if char == " ":
                position += 1
                continue
            if char == "#":
                tokens.append(
                    Token("COMMENT", raw_line[position:], line_number, position + 1, here)
                )
                break

            if char == '"':
                end = raw_line.find('"', position + 1)
                if end == -1:
                    diagnostics.append(
                        Diag(
                            code="AEDX0004",
                            message="unterminated string literal",
                            span=Span(line_number, position + 1, here),
                            params={},
                            fixit='add the closing `"`',
                        )
                    )
                    break
                tokens.append(
                    Token(
                        "STRING",
                        raw_line[position + 1 : end],
                        line_number,
                        position + 1,
                        here,
                    )
                )
                position = end + 1
                continue

            if char.isdigit() or (
                char == "-"
                and position + 1 < len(raw_line)
                and raw_line[position + 1].isdigit()
            ):
                match = _QUANTITY_RE.match(raw_line, position)
                if match:
                    text = match.group(0)
                    try:
                        parse_quantity(text)
                    except QuantityError as exc:
                        diagnostics.append(
                            Diag(
                                code="AEDX0005",
                                message=str(exc),
                                span=Span(line_number, position + 1, here, len(text)),
                                params={"literal": text},
                            )
                        )
                    tokens.append(
                        Token("QUANTITY", text, line_number, position + 1, here)
                    )
                    position += len(text)
                    continue
                # Not a quantity: a bare number. Dimensionless assertion
                # bounds (duty cycle) and array sizes look like this, and
                # an integer-only fallback would lex `0.524` as `0`, `.`,
                # `524` and then fail somewhere unrelated.
                match = _NUMBER_RE.match(raw_line, position)
                tokens.append(
                    Token("NUMBER", match.group(0), line_number, position + 1, here)
                )
                position += len(match.group(0))
                continue

            match = _NAME_RE.match(raw_line, position)
            if match:
                tokens.append(
                    Token("NAME", match.group(0), line_number, position + 1, here)
                )
                position += len(match.group(0))
                continue

            if char in _OPERATORS:
                if char in "([":
                    bracket_depth += 1
                    open_brackets.append((line_number, position + 1, here))
                elif char in ")]":
                    bracket_depth = max(0, bracket_depth - 1)
                    if open_brackets:
                        open_brackets.pop()
                tokens.append(Token("OP", char, line_number, position + 1, here))
                position += 1
                continue

            diagnostics.append(
                Diag(
                    code="AEDX0006",
                    message=f"unexpected character {char!r}",
                    span=Span(line_number, position + 1, here),
                    params={"character": char},
                )
            )
            position += 1

        if bracket_depth == 0 and tokens and tokens[-1].kind != "NEWLINE":
            tokens.append(
                Token("NEWLINE", "", line_number, len(raw_line) + 1, line_start + len(raw_line))
            )

    if bracket_depth != 0:
        opened_line, opened_column, opened_offset = (
            open_brackets[0] if open_brackets else (line_number, 1, offset)
        )
        diagnostics.append(
            Diag(
                code="AEDX0007",
                message=(
                    f"{bracket_depth} bracket(s) left open; the outermost was "
                    f"opened on line {opened_line} and never closed"
                ),
                span=Span(opened_line, opened_column, opened_offset),
                params={"depth": bracket_depth, "opened_line": opened_line},
                fixit="close the bracket",
            )
        )

    while len(indents) > 1:
        indents.pop()
        tokens.append(Token("DEDENT", "", line_number + 1, 1, offset))
    tokens.append(Token("EOF", "", line_number + 1, 1, offset))

    if diagnostics:
        raise ParseFailure(diagnostics)
    return tokens


def strip_comments(tokens: list[Token]) -> list[Token]:
    """Drop COMMENT tokens and the NEWLINEs of comment-only lines.

    Parsers work on the stripped stream; the measurement works on the source
    text, so comments still cost tokens exactly as they should.
    """
    out: list[Token] = []
    for token in tokens:
        if token.kind == "COMMENT":
            continue
        if token.kind == "PRAGMA":
            out.append(token)
            continue
        if (
            token.kind == "NEWLINE"
            and out
            and out[-1].kind in ("NEWLINE", "INDENT", "DEDENT")
        ):
            continue
        if token.kind == "NEWLINE" and not out:
            continue
        out.append(token)
    return out
