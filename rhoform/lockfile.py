"""Lockfile v0 (R55, AMB-59): rhoform.lock, read and checked.

spec/language/08-packages.md ("The lockfile") is normative; this says how
the code reads it. One file at the compile root holds up to three sections
that share one framing (R14a L4): `packages` (resolution, L5), `parts` (the
D1 picks) and `renames` (the I2 ledger). Each section is `{inputs,
entries}`; an input is a file's path and the sha256 of its exact bytes, and
a section is stale when an input it records is missing or its bytes moved.
The file is OPTIONAL in this version (decision D30): with none, every
section is unlocked, which spec 08 records as a deviation from L3.

CANONICAL BYTES. A lockfile's bytes are `json.dumps(doc,
ensure_ascii=False, sort_keys=True, indent=2)` plus one LF, which
JavaScript's `JSON.stringify(sorted, null, 2)` also writes: the schema's
keys are ASCII, so code-point and UTF-16 key orders agree, and both escape
exactly `"`, `\\` and the C0 controls. A reader refuses other bytes, so one
lockfile state is one byte string and a diff of two is a diff of states.
`canonical_bytes` writes them, and `_Layout` writes them while recording
where each value lands, so every later span is exact.

WHAT IS CHECKED, in order, each step only once the one before it passed
(`parse`): strict UTF-8 JSON (RHO2070), read by a reader of this module's
own (`_Reader`), so a refusal's reason and position are the same on every
interpreter; the canonical layout (RHO2071,
alone, with a fix-it that rewrites the file); the version (RHO2072); the
schema, rhoform/lockfile.schema.json, and the invariants it cannot state --
array order, selector uniqueness, each entry naming an input of its own
section, the reserved `rhoform/` paths (RHO2073); and what version 0
refuses rather than ignores, a rename-ledger entry and a package
`content_hash` (RHO2075). `check_packages` then holds the packages section
to the manifests the compilation read (RHO2074). A pick is verified by the
check stage's `parts` pass, which reads the record (rhoform/check/parts.py);
nothing here opens a record.

HERMETIC. This module opens only what it is handed and, once per process,
its own schema file; it lists a directory only to match a path's spelling
(`locate`), and touches no network.

WRITING. Nothing in this toolchain writes rhoform.lock yet (spec 08
deviations). A writer replaces only its own section, re-serializes the
whole file canonically and writes it atomically, so the other sections come
out byte-identical: `replace_section` is that contract's pure half, and
`canonical_bytes`, `input_entry` and `constraints_digest` build what a
section holds.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import os
import re

from .diagnostics import Edit, FixIt, span_from_bytes

LOCKFILE = "rhoform.lock"
SCHEMA_PATH = Path(__file__).resolve().parent / "lockfile.schema.json"
# The toolchain's own tree: a lockfile path beginning `rhoform/` names a
# file under it, as the source map's `rhoform/lib/` paths do.
TOOLCHAIN = Path(__file__).resolve().parents[1]
TOOLCHAIN_PREFIX = "rhoform/"
STORE_PREFIX = "rhoform/parts/"
RECORD_SUFFIX = ".part.json"
MANIFEST = "rhoform.toml"
SUPPORTED = (0,)
SECTIONS = ("packages", "parts", "renames")
# Deeper than any lockfile the schema describes (five levels) and shallow
# enough that no walk here meets the interpreter's stack limit first.
MAX_NESTING = 32
# Why a query finds no pick (spec 08): no rhoform.lock at the compile root,
# no parts section in it, or no entry for the selector.
UNLOCKED = ("no-lockfile", "no-parts-section", "no-pick")
UNAVAILABLE_REASONS = ("canonical-archive-unavailable",)

# Every object's keys, required ones marked, as spec 08 restates them
# (reconciled against key_rows). The schema is the normative shape; these
# are what the code and the spec read.
KEYS = (
    ("the lockfile", (("lockfile_version", True), ("packages", False),
                      ("parts", False), ("renames", False))),
    ("a section", (("entries", True), ("inputs", True))),
    ("an input", (("path", True), ("sha256", True))),
    ("a package entry", (("content_hash", True), ("manifest", True),
                         ("name", True), ("requires_rhoform", True),
                         ("source", True), ("unavailable_reason", False),
                         ("version", True))),
    ("a keyed pick", (("key", True), ("manufacturer", True), ("mpn", True),
                      ("part_id", True), ("record", True))),
    ("an instance pick", (("constraints", True), ("design", True),
                          ("instance", True), ("manufacturer", True),
                          ("mpn", True), ("part_id", True),
                          ("record", True))),
    ("a rename", (("design", True), ("origin", True), ("path", True))),
)


def key_rows() -> tuple:
    """(object, key, required) for every key a lockfile object may hold."""
    return tuple((what, key, "yes" if required else "no")
                 for what, keys in KEYS for key, required in keys)


def code_rows() -> tuple:
    """(code, slug, severity) of every lockfile code."""
    from .codeset.lockfile import CODES

    return tuple((entry.code, entry.slug, entry.severity) for entry in CODES)


# ---- canonical bytes --------------------------------------------------------

class _Number(str):
    """A JSON number that is not a plain integer, kept as its token: a
    fraction or an exponent, or an integer too long to convert. No member
    of a version 0 lockfile holds one, so the schema refuses it, but the
    layout check writes it back exactly as it was written."""


def _integer(token: str):
    return int(token) if len(token) <= 18 else _Number(token)


def _pointer(parent: str, key) -> str:
    token = str(key).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{token}"


class _Layout:
    """The canonical text of a document, and the byte span of every value
    (by JSON pointer) and of every object key (by the pointer of its
    value) in it."""

    def __init__(self, document):
        self.chunks: list[str] = []
        self.position = 0
        self.values: dict[str, tuple[int, int]] = {}
        self.keys: dict[str, tuple[int, int]] = {}
        self._write(document, 0, "")
        self._emit("\n")

    def _emit(self, text: str) -> None:
        self.chunks.append(text)
        self.position += len(text.encode("utf-8"))

    def _write(self, node, depth: int, pointer: str) -> None:
        start = self.position
        pad = "  " * (depth + 1)
        if isinstance(node, _Number):
            self._emit(str(node))
        elif isinstance(node, str):
            self._emit(json.dumps(node, ensure_ascii=False))
        elif node is True or node is False or node is None \
                or isinstance(node, int):
            self._emit(json.dumps(node))
        elif isinstance(node, list):
            if not node:
                self._emit("[]")
            else:
                self._emit("[\n")
                for index, item in enumerate(node):
                    self._emit(pad)
                    self._write(item, depth + 1, _pointer(pointer, index))
                    self._emit(",\n" if index < len(node) - 1 else "\n")
                self._emit("  " * depth + "]")
        elif isinstance(node, dict):
            if not node:
                self._emit("{}")
            else:
                self._emit("{\n")
                items = sorted(node.items())
                for index, (key, value) in enumerate(items):
                    self._emit(pad)
                    where = _pointer(pointer, key)
                    begin = self.position
                    self._emit(json.dumps(key, ensure_ascii=False))
                    self.keys[where] = (begin, self.position)
                    self._emit(": ")
                    self._write(value, depth + 1, where)
                    self._emit(",\n" if index < len(items) - 1 else "\n")
                self._emit("  " * depth + "}")
        else:
            raise TypeError(f"{node!r} is not a JSON value")
        self.values[pointer] = (start, self.position)

    @property
    def text(self) -> str:
        return "".join(self.chunks)


def canonical_bytes(document) -> bytes:
    """The canonical bytes of a lockfile document."""
    return _Layout(document).text.encode("utf-8")


def digest(data: bytes) -> str:
    """The `sha256:` hash of exact bytes, as every input records it."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def input_entry(path: str, data: bytes) -> dict:
    """The input a section records for the file at `path` holding `data`."""
    return {"path": path, "sha256": digest(data)}


def replace_section(data: bytes | None, name: str, section) -> bytes:
    """The bytes of the lockfile `data` (None: no lockfile yet) with the
    section `name` replaced by `section` (None removes it), every other
    section unchanged: a writer's half of the writer contract. Raises
    ValueError when `data` is not a canonical lockfile of a supported
    version, which a writer must not paper over."""
    if name not in SECTIONS:
        raise ValueError(f"{name!r} is not a lockfile section")
    if data is None:
        document = {"lockfile_version": SUPPORTED[-1]}
    else:
        document = _decode(data)
        if canonical_bytes(document) != data \
                or document.get("lockfile_version") not in SUPPORTED:
            raise ValueError("not a canonical lockfile this toolchain reads")
    if section is None:
        document.pop(name, None)
    else:
        document[name] = section
    return canonical_bytes(document)


def _exact(value: Decimal) -> str:
    """A Decimal's exact value as a plain decimal string: no exponent, no
    trailing fractional zero, and no negative zero, so two spellings of one
    value are one string. Formatting rounds nothing; no context is used."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def constraints_digest(constraints: dict) -> str:
    """The digest an instance pick records of the part constraints it was
    made for (spec 08): rhoform-canonical-json/1 over each constraint's
    EXACT elaborated value, a quantity as its normal-form unit and decimal
    strings, never as the IR's doubles (amendment engineering 11)."""
    from .ir import canonical_bytes as canonical_json

    encoded = {}
    for name, value in sorted(constraints.items()):
        if isinstance(value, bool) or isinstance(value, str):
            encoded[name] = value
        elif isinstance(value, int):
            encoded[name] = {"integer": str(value)}
        else:
            quantity = {"unit": value.unit, "value": _exact(value.value)}
            if value.tolerance is not None:
                quantity["min"] = _exact(value.tolerance[0])
                quantity["max"] = _exact(value.tolerance[1])
            encoded[name] = quantity
    return digest(canonical_json(encoded))


# ---- reading ----------------------------------------------------------------

class _Refused(ValueError):
    """Bytes that are not a lockfile's JSON, with where (byte offsets)."""

    def __init__(self, reason: str, start: int, end: int):
        super().__init__(reason)
        self.reason, self.start, self.end = reason, start, end


_WHITESPACE = " \t\n\r"
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}
_WORDS = (("true", True), ("false", False), ("null", None))
_CONSTANTS = ("NaN", "Infinity", "-Infinity")


class _Reader:
    """RFC 8259 JSON over decoded text, strictly, in a vocabulary of reasons
    and positions of its own: the standard library's decoder words its
    errors, and places some, differently from one Python to the next, and a
    diagnostic's params and span may not depend on the interpreter. Refused:
    a repeated key in one object, NaN and infinities, a lone surrogate
    escape, and nesting past MAX_NESTING. A number that is not a plain
    integer is kept as its token (_Number)."""

    def __init__(self, data: bytes):
        self.text = data.decode("utf-8")
        self.at = 0

    def offset(self, index: int) -> int:
        return len(self.text[:index].encode("utf-8"))

    def refuse(self, reason, start=None, end=None):
        start = self.at if start is None else start
        end = start if end is None else end
        raise _Refused(reason, self.offset(start), self.offset(end))

    def skip(self):
        while self.at < len(self.text) and self.text[self.at] in _WHITESPACE:
            self.at += 1

    def document(self):
        self.skip()
        value = self.value(0)
        self.skip()
        if self.at < len(self.text):
            self.refuse("there is more after the document")
        return value

    def value(self, depth: int):
        text, at = self.text, self.at
        if at >= len(text):
            self.refuse("a value is missing")
        char = text[at]
        if char in "{[":
            if depth == MAX_NESTING:
                self.refuse(f"it nests more than {MAX_NESTING} levels deep")
            return self.obj(depth) if char == "{" else self.array(depth)
        if char == '"':
            return self.string()
        for word, meaning in _WORDS:
            if text.startswith(word, at):
                self.at += len(word)
                return meaning
        for word in _CONSTANTS:
            if text.startswith(word, at):
                self.refuse(f"`{word}` is not a JSON number", at,
                            at + len(word))
        number = _NUMBER.match(text, at)
        if number is None or number.end() == at:
            self.refuse("a value is expected here")
        self.at = number.end()
        token = number.group()
        if number.group(1) is None and number.group(2) is None:
            return _integer(token)
        return _Number(token)

    def obj(self, depth: int) -> dict:
        self.at += 1
        found = {}
        self.skip()
        if self.text.startswith("}", self.at):
            self.at += 1
            return found
        while True:
            self.skip()
            if not self.text.startswith('"', self.at):
                self.refuse("an object key, a string, is expected here")
            start = self.at
            key = self.string()
            if key in found:
                self.refuse(f"the key {json.dumps(key, ensure_ascii=False)} "
                            "appears twice in one object", start, self.at)
            self.skip()
            if not self.text.startswith(":", self.at):
                self.refuse("`:` is expected after an object key")
            self.at += 1
            self.skip()
            found[key] = self.value(depth + 1)
            self.skip()
            if self.text.startswith("}", self.at):
                self.at += 1
                return found
            if not self.text.startswith(",", self.at):
                self.refuse("`,` or `}` is expected here")
            self.at += 1

    def array(self, depth: int) -> list:
        self.at += 1
        found = []
        self.skip()
        if self.text.startswith("]", self.at):
            self.at += 1
            return found
        while True:
            self.skip()
            found.append(self.value(depth + 1))
            self.skip()
            if self.text.startswith("]", self.at):
                self.at += 1
                return found
            if not self.text.startswith(",", self.at):
                self.refuse("`,` or `]` is expected here")
            self.at += 1

    def string(self) -> str:
        text = self.text
        start = self.at
        self.at += 1
        out = []
        while True:
            if self.at >= len(text):
                self.refuse("a string is not closed", start)
            char = text[self.at]
            if char == '"':
                self.at += 1
                return "".join(out)
            if char < " ":
                self.refuse("a control character must be escaped in a "
                            "string")
            if char != "\\":
                out.append(char)
                self.at += 1
                continue
            escape = text[self.at + 1:self.at + 2]
            if escape in _ESCAPES:
                out.append(_ESCAPES[escape])
                self.at += 2
                continue
            if escape != "u":
                self.refuse("an escape that JSON does not have", self.at,
                            self.at + 2)
            unit = self.unit(self.at)
            if 0xDC00 <= unit <= 0xDFFF or (0xD800 <= unit <= 0xDBFF and not (
                    text.startswith("\\u", self.at + 6)
                    and 0xDC00 <= self.unit(self.at + 6) <= 0xDFFF)):
                self.refuse("a string in it holds a lone surrogate escape, "
                            "which UTF-8 cannot carry", self.at, self.at + 6)
            if 0xD800 <= unit <= 0xDBFF:
                low = self.unit(self.at + 6)
                out.append(chr(0x10000 + ((unit - 0xD800) << 10)
                               + (low - 0xDC00)))
                self.at += 12
            else:
                out.append(chr(unit))
                self.at += 6

    def unit(self, at: int) -> int:
        digits = self.text[at + 2:at + 6]
        if len(digits) != 4 or any(c not in "0123456789abcdefABCDEF"
                                   for c in digits):
            self.refuse("a `\\u` escape takes four hex digits", at, at + 2)
        return int(digits, 16)


def _decode(data: bytes):
    """The document `data` holds, numbers that are not plain integers kept
    as tokens. Raises _Refused, naming where."""
    try:
        reader = _Reader(data)
    except UnicodeDecodeError as exc:
        raise _Refused("it is not UTF-8", exc.start, exc.start) from None
    return reader.document()


def _plain(node):
    """`node` with each kept number token as the Decimal it spells, which a
    JSON Schema validator types as a number, never as a string."""
    if isinstance(node, _Number):
        try:
            return Decimal(node)
        except ArithmeticError:  # pragma: no cover - the decoder's tokens
            return float("nan")
    if isinstance(node, dict):
        return {key: _plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_plain(item) for item in node]
    return node


_VALIDATOR = None


def _validator():
    """The schema's validator, read once. Raises ImportError when the
    pinned jsonschema is missing: an unavailable check, never a pass."""
    global _VALIDATOR
    import jsonschema

    if _VALIDATOR is None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        _VALIDATOR = jsonschema.validators.validator_for(schema)(schema)
    return _VALIDATOR


@dataclass(frozen=True)
class Pick:
    """One parts entry: a keyed pick (`key` set) or an instance pick
    (`design` and `instance` set, with the `constraints` digest it was made
    for). `revision` is the sha256 the section's input records for the
    record, and `pointer` the entry's place in the file."""

    part_id: str
    manufacturer: str
    mpn: str
    record: str
    revision: str
    pointer: str
    key: str | None = None
    design: str | None = None
    instance: str | None = None
    constraints: str | None = None


@dataclass(frozen=True)
class Unlocked:
    """No pick: `reason` is one of UNLOCKED."""

    reason: str


class Lockfile:
    """A lockfile that passed every check `parse` makes: its bytes, its
    document, and where each value sits in the bytes."""

    path = LOCKFILE

    def __init__(self, data: bytes, document: dict, layout: _Layout):
        self.data = data
        self.document = document
        self._values = layout.values
        self._keys = layout.keys
        parts = document.get("parts")
        self._keyed, self._instances = {}, {}
        if parts is not None:
            revisions = {item["path"]: item["sha256"]
                         for item in parts["inputs"]}
            for index, entry in enumerate(parts["entries"]):
                pick = Pick(entry["part_id"], entry["manufacturer"],
                            entry["mpn"], entry["record"],
                            revisions[entry["record"]],
                            f"/parts/entries/{index}", entry.get("key"),
                            entry.get("design"), entry.get("instance"),
                            entry.get("constraints"))
                if pick.key is not None:
                    self._keyed[pick.key] = pick
                else:
                    self._instances[(pick.design, pick.instance)] = pick

    def section(self, name: str):
        return self.document.get(name)

    def pick_key(self, key: str):
        """The keyed pick for a `part "key"`, or Unlocked."""
        if self.section("parts") is None:
            return Unlocked("no-parts-section")
        return self._keyed.get(key, Unlocked("no-pick"))

    def pick_instance(self, design: str, instance: str):
        """The instance pick for an identity path of a design, or
        Unlocked."""
        if self.section("parts") is None:
            return Unlocked("no-parts-section")
        return self._instances.get((design, instance), Unlocked("no-pick"))

    def instance_picks(self, design: str) -> tuple:
        """Every instance pick of `design`, in file order."""
        return tuple(pick for (owner, _path), pick in self._instances.items()
                     if owner == design)

    def input_pointer(self, section: str, path: str) -> str:
        index = next(i for i, item in enumerate(self.document[section]
                                                 ["inputs"])
                     if item["path"] == path)
        return f"/{section}/inputs/{index}"

    def span(self, pointer: str, part: str = "value"):
        """The span of the value (or key) at `pointer`, else of its nearest
        enclosing value."""
        return _span(self.data, self._values, self._keys, pointer, part)


def pick_key(lock, key: str):
    """Lockfile.pick_key, with no lockfile at all unlocked too."""
    return Unlocked("no-lockfile") if lock is None else lock.pick_key(key)


def pick_instance(lock, design: str, instance: str):
    return Unlocked("no-lockfile") if lock is None \
        else lock.pick_instance(design, instance)


def _span(data, values, keys, pointer, part="value"):
    if part == "key" and pointer in keys:
        start, end = keys[pointer]
    else:
        while pointer and pointer not in values:
            pointer = pointer[:pointer.rfind("/")]
        start, end = values.get(pointer, (0, len(data)))
    return span_from_bytes(LOCKFILE, data, start, end)


def _first_line_differing(data: bytes, canonical: bytes):
    """(1-based line, byte start, byte end) of the line of `data` holding
    the first byte where it and `canonical` differ."""
    position = next((i for i, (a, b) in enumerate(zip(data, canonical))
                     if a != b), min(len(data), len(canonical)))
    start = data.rfind(b"\n", 0, position) + 1
    end = data.find(b"\n", position)
    end = len(data) if end < 0 else end
    if start == end and end < len(data):
        end += 1
    return data.count(b"\n", 0, start) + 1, start, end


def parse(data: bytes, sink):
    """The Lockfile `data` holds, or None when any check refused it, each
    problem reported into `sink`. Raises ImportError when the pinned
    jsonschema is missing."""
    try:
        document = _decode(data)
    except _Refused as exc:
        sink.add("RHO2070", {"reason": exc.reason},
                 primary=span_from_bytes(LOCKFILE, data, exc.start, exc.end))
        return None
    layout = _Layout(document)
    canonical = layout.text.encode("utf-8")
    if canonical != data:
        line, start, end = _first_line_differing(data, canonical)
        whole = span_from_bytes(LOCKFILE, data, 0, len(data))
        sink.add("RHO2071", {"line": line},
                 primary=span_from_bytes(LOCKFILE, data, start, end),
                 fixits=(FixIt("rewrite rhoform.lock in canonical layout",
                               "machine-applicable",
                               (Edit(whole, layout.text),)),))
        return None
    values, keys = layout.values, layout.keys

    def at(pointer, part="value"):
        return _span(data, values, keys, pointer, part)

    version = document.get("lockfile_version") \
        if isinstance(document, dict) else None
    if isinstance(version, bool) or version not in SUPPORTED:
        declared = "missing" if not isinstance(document, dict) \
            or "lockfile_version" not in document \
            else shown(document["lockfile_version"])
        sink.add("RHO2072", {"version": declared,
                             "supported": ", ".join(map(str, SUPPORTED))},
                 primary=at("/lockfile_version"))
        return None
    before = sink.counts()["error"]
    for pointer, reason in schema_problems(document):
        sink.add("RHO2073", {"pointer": pointer or "/", "reason": reason},
                 primary=at(pointer))
    if sink.counts()["error"] == before:
        for pointer, reason in invariant_problems(document):
            sink.add("RHO2073", {"pointer": pointer, "reason": reason},
                     primary=at(pointer))
    if sink.counts()["error"] == before:
        for pointer, entry, owner in refusals(document):
            sink.add("RHO2075", {"pointer": pointer, "entry": entry,
                                 "owner": owner}, primary=at(pointer))
    if sink.counts()["error"] > before:
        return None
    return Lockfile(data, document, layout)


def shown(value) -> str:
    """A scalar as the lockfile spells it, a container by its kind."""
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "an array"
    return _Layout(value).text.rstrip("\n")


def schema_problems(document) -> list:
    """(pointer, reason) for every way `document` breaks the version 0
    schema, sorted. A key no object of its kind may hold is named by its
    own pointer, so its finding spans it. Raises ImportError when
    jsonschema is missing."""
    found = []
    for error in _validator().iter_errors(_plain(document)):
        pointer = "".join(_pointer("", part)
                          for part in error.absolute_path)
        if error.validator == "additionalProperties" \
                and isinstance(error.instance, dict):
            allowed = set(error.schema.get("properties", {}))
            for key in sorted(set(error.instance) - allowed):
                found.append((_pointer(pointer, key),
                              f"`{key}` is not a key this object may hold"))
            continue
        found.append((pointer, error.message))
    return sorted(set(found))


def _path_problem(path: str, section: str) -> str | None:
    """Why `path` cannot be an input of `section`, or None."""
    if section == "packages":
        if path.startswith(TOOLCHAIN_PREFIX):
            return ("names a toolchain file, and the toolchain bundles no "
                    "package manifest")
        if path != MANIFEST and not path.endswith("/" + MANIFEST):
            return f"is not a manifest; a packages input is a {MANIFEST}"
    elif section == "parts":
        if not path.endswith(RECORD_SUFFIX):
            return f"is not a part record; a parts input ends {RECORD_SUFFIX}"
        if path.startswith(TOOLCHAIN_PREFIX) \
                and not path.startswith(STORE_PREFIX):
            return (f"names a toolchain file outside its part store "
                    f"`{STORE_PREFIX}`")
    return None


def _order_problems(rows, where, what, problems):
    """`rows` is [(sort key, pointer)]: each key once, in ascending order."""
    seen = {}
    previous = None
    for key, pointer in rows:
        if key in seen:
            problems.append((pointer, f"repeats the {what} of {seen[key]}; "
                             f"each {what} appears once"))
        elif previous is not None and key < previous:
            problems.append((pointer, f"is out of order: {where} are "
                             f"sorted by {what}"))
        seen.setdefault(key, pointer)
        previous = key if previous is None or key > previous else previous


def invariant_problems(document) -> list:
    """(pointer, reason) for every version 0 invariant a schema-valid
    `document` breaks, in file order: order, uniqueness, references from
    entries to inputs, input paths, and the renames rules."""
    from .package import name_problem, range_problem

    problems = [(_pointer("", key), "an x_ member is reserved for "
                 "annotations no compiler reads, and a lockfile holds none")
                for key in sorted(document) if key.startswith("x_")]
    for section in SECTIONS:
        body = document.get(section)
        if body is None:
            continue
        inputs = body["inputs"]
        _order_problems([(item["path"], f"/{section}/inputs/{i}/path")
                         for i, item in enumerate(inputs)],
                        "inputs", "path", problems)
        for i, item in enumerate(inputs):
            problem = _path_problem(item["path"], section)
            if problem is not None:
                problems.append((f"/{section}/inputs/{i}/path",
                                 f"`{item['path']}` {problem}"))
        recorded = {item["path"] for item in inputs}
        entries = body["entries"]
        if section == "packages":
            _order_problems([(entry["name"], f"/packages/entries/{i}/name")
                             for i, entry in enumerate(entries)],
                            "package entries", "name", problems)
            for i, entry in enumerate(entries):
                where = f"/packages/entries/{i}"
                for key, problem in (
                        ("name", name_problem(entry["name"])),
                        ("requires_rhoform",
                         range_problem(entry["requires_rhoform"]))):
                    if problem is not None:
                        problems.append((f"{where}/{key}", problem))
                root = entry["source"]["path"]
                want = MANIFEST if root == "." else f"{root}/{MANIFEST}"
                if entry["manifest"] != want:
                    problems.append((
                        f"{where}/manifest",
                        f"`{entry['manifest']}` is not the manifest of the "
                        f"package root `{root}`, which is `{want}`"))
                elif entry["manifest"] not in recorded:
                    problems.append((
                        f"{where}/manifest",
                        f"`{entry['manifest']}` is not among the section's "
                        "inputs, so nothing records its bytes"))
        elif section == "parts":
            keyed = [(entry["key"], f"/parts/entries/{i}/key")
                     for i, entry in enumerate(entries) if "key" in entry]
            picked = [((entry["design"], entry["instance"]),
                       f"/parts/entries/{i}/instance")
                      for i, entry in enumerate(entries)
                      if "key" not in entry]
            first_instance = next((i for i, entry in enumerate(entries)
                                   if "key" not in entry), None)
            if first_instance is not None and any(
                    "key" in entry for entry in entries[first_instance:]):
                late = next(i for i, entry in enumerate(entries)
                            if i > first_instance and "key" in entry)
                problems.append((f"/parts/entries/{late}",
                                 "is a keyed pick after an instance pick; "
                                 "keyed picks come first"))
            _order_problems(keyed, "keyed picks", "key", problems)
            _order_problems(picked, "instance picks", "design and instance",
                            problems)
            for i, entry in enumerate(entries):
                if entry["record"] not in recorded:
                    problems.append((
                        f"/parts/entries/{i}/record",
                        f"`{entry['record']}` is not among the section's "
                        "inputs, so nothing records its revision"))
        else:
            _order_problems([((entry["design"], entry["path"]),
                              f"/renames/entries/{i}/path")
                             for i, entry in enumerate(entries)],
                            "rename entries", "design and path", problems)
            origins = {}
            for i, entry in enumerate(entries):
                where = f"/renames/entries/{i}"
                if entry["path"] == entry["origin"]:
                    problems.append((f"{where}/origin",
                                     "names the path itself; a rename "
                                     "moves an identity to another path"))
                key = (entry["design"], entry["origin"])
                if key in origins:
                    problems.append((f"{where}/origin",
                                     f"is also the origin of {origins[key]}; "
                                     "one identity has one current path"))
                origins.setdefault(key, where)
    return problems


def refusals(document) -> list:
    """(pointer, entry, owner) for every entry version 0 refuses rather
    than ignores: a rename-ledger entry, which nothing applies until R27,
    and a package content_hash, which nothing can verify until the
    canonical archive exists."""
    found = []
    for i, entry in enumerate((document.get("packages") or {})
                              .get("entries", ())):
        if entry["content_hash"] is not None:
            found.append((f"/packages/entries/{i}/content_hash",
                          "a package content_hash",
                          "the canonical package archive, R14a G8-G10, "
                          "AMB-150"))
    for i, _entry in enumerate((document.get("renames") or {})
                               .get("entries", ())):
        found.append((f"/renames/entries/{i}", "a rename-ledger entry",
                      "the rename ledger, R27, AMB-62"))
    return found


def check_packages(lock: Lockfile, packages, sink) -> None:
    """Hold the packages section, when there is one, to the packages this
    compilation read (rhoform.package.Package, each with its manifest's
    bytes): every manifest is an input with its bytes' hash, and every
    package has an entry agreeing with its manifest on source, version and
    language range. Entries and inputs no package of this compilation
    names belong to other compilations of the workspace and are not
    checked (spec 08)."""
    from .package import language_versions, range_admits

    section = lock.section("packages")
    if section is None:
        return
    inputs = {item["path"]: (i, item["sha256"])
              for i, item in enumerate(section["inputs"])}
    entries = {entry["name"]: (i, entry)
               for i, entry in enumerate(section["entries"])}
    supported = language_versions()

    def stale(subject, problem, pointer):
        sink.add("RHO2074", {"subject": subject, "problem": problem},
                 primary=lock.span(pointer))

    for package in sorted(packages, key=lambda p: p.root):
        if package.manifest is None:
            continue
        found = inputs.get(package.manifest)
        if found is None:
            stale(package.manifest, "it is not among the section's inputs; "
                  "a packages section records every manifest a compilation "
                  "reads", "/packages/inputs")
        elif found[1] != digest(package.data):
            stale(package.manifest,
                  f"its bytes hash to {digest(package.data)}, not the "
                  f"recorded {found[1]}: it changed since it was locked",
                  f"/packages/inputs/{found[0]}/sha256")
        if package.name is None or package.requires is None:
            continue  # its manifest's own defect is reported there
        located = entries.get(package.name)
        if located is None:
            stale(package.name, "it has no entry; a packages section has "
                  "one for every package a compilation reads",
                  "/packages/entries")
            continue
        index, entry = located
        where = f"/packages/entries/{index}"
        root = package.root or "."
        if entry["source"]["path"] != root:
            stale(package.name, f"it is locked at `{entry['source']['path']}`"
                  f", and this compilation reads it from `{root}`",
                  f"{where}/source/path")
        if entry["version"] != package.version:
            stale(package.name, f"it is locked at version {entry['version']}"
                  f", and its manifest declares {package.version}",
                  f"{where}/version")
        locked = entry["requires_rhoform"]
        if not _within(locked, package.requires):
            stale(package.name, f"its locked range `{locked}` is not "
                  f"contained in its manifest's `requires-rhoform = "
                  f"\"{package.requires}\"`", f"{where}/requires_rhoform")
        elif not any(range_admits(locked, v) for v in supported):
            stale(package.name, f"its locked range `{locked}` admits none of "
                  f"the language versions this toolchain implements "
                  f"({', '.join(supported)})", f"{where}/requires_rhoform")


def _within(inner: str, outer: str) -> bool:
    """Whether every version the range `inner` admits, `outer` admits."""
    from .package import range_admits

    if inner[0] == "=":
        return range_admits(outer, inner[1:])
    if outer[0] == "=":
        return False
    base = inner[1:]
    if not range_admits(outer, base):
        return False
    # Both are compatibility windows holding `base`: inner's lies inside
    # outer's when outer's floor is no higher and the two windows end at
    # one bound, which a ^ window's first non-zero number fixes.
    def window(text):
        major, minor, _patch = text.split("-")[0].split(".")
        return (major,) if major != "0" else (major, minor)

    return window(inner[1:]) == window(outer[1:])


# ---- where a lockfile is ----------------------------------------------------

def locate(root, path: str):
    """The file `path` (a lockfile input path) names, from the compile root
    `root`, as (Path, None), or (None, why it names none). A `rhoform/`
    path is the toolchain's own file. Every name matches the file system's
    spelling exactly, letter case included, so the directories on the way
    are listed for that and nothing else; and a compile root's file a
    symbolic link leads out of the root names nothing."""
    toolchain = path.startswith(TOOLCHAIN_PREFIX)
    base = TOOLCHAIN if toolchain else Path(root)
    walk = base
    for segment in path.split("/"):
        try:
            names = os.listdir(walk)
        except OSError as exc:
            return None, (f"lies under `{walk.name}`, which cannot be listed "
                          f"to match its spelling ({exc.strerror})")
        if segment not in names:
            close = sorted(name for name in names
                           if name.casefold() == segment.casefold())
            if close:
                return None, (f"does not exist as spelled: the file system "
                              f"spells `{segment}` as `{close[0]}`, and "
                              "names match exactly, letter case included")
            return None, "does not exist"
        walk = walk / segment
    if not os.path.isfile(walk):
        return None, "is not a file"
    real, real_base = os.path.realpath(walk), os.path.realpath(base)
    if not real.startswith(real_base.rstrip(os.sep) + os.sep):
        return None, ("leads outside the "
                      + ("toolchain" if toolchain else "compile root")
                      + " through a symbolic link, and nothing outside is "
                      "read")
    return walk, None
