"""Part data (D3): read, check and bind part records.

The static tier's view of a part record (parts/part-data.schema.json for
version 0, parts/part-data.v1.schema.json for version 1). Five things live
here, so the compiler and the repository's part-data gate apply one set of
rules rather than two that drift:

  - READING. `parse` keeps every number exact: a fraction becomes a
    `decimal.Decimal` built from the digits as written and an integer an
    `int`, so `0.3` is `Decimal("0.3")` and converts to `Fraction(3, 10)`
    with nothing lost. A float would make `0.1 A + 0.2 A <= 0.3 A` false,
    which is exactly the comparison a budget makes at its boundary.
    Duplicate keys, NaN and Infinity are refused rather than resolved, and
    so are a lone surrogate escape and nesting past MAX_NESTING: whatever
    a file holds, its bytes come back as a record or a PartDataError.
  - IDENTITY. A record's revision is the sha256 of its file's exact bytes.
    That is only a content identity if the bytes are a function of the
    content, so a record must be in CANONICAL LAYOUT (`layout_problems`):
    UTF-8, LF line ends, two-space indent, keys sorted, every number spelled
    as its author wrote it, one trailing LF. "As written" is checked by a
    round trip that keeps each number's token, so the layout rule never
    rewrites a value and `4.0` stays `4.0`.
  - CHECKING. `validate` holds a record to the schema of the version it
    declares and refuses a version this module does not implement. `lint`
    holds it to the cross-references no JSON Schema can state (L1-L22,
    listed at `lint_problems`). parts/lint-part-data.py is a thin gate over
    these functions.
  - BINDING. `bind` joins a record to one component definition through the
    record's `implements` map and nothing else: no name, case or designator
    guessing, because `ctl` is not `CONT` and `p3v3` is not `3V3`. The
    design's role is authoritative; the record's role only has to be
    compatible with it (`compatible`), except on a definition that models
    one part (PART_SPECIFIC), where the two must be equal.
  - HONEST VIEWS. Every value a binding hands out carries its statistic and
    whether it is a guarantee: `min` and `max` are, `typ` and `peak` never
    are, and neither is any value whose provenance says `estimated` or
    `unverified`. A relative bound stays symbolic (`Relative`); evaluating
    it against the referenced pin's net is the checker's job, at one corner.

HERMETIC. partdata opens the path it is given and, once per process per
schema_version, the toolchain's own schema file for that version
(parts/part-data[.vN].schema.json); it lists nothing, starts no process, and
opens no network connection.
"""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "parts"
# One immutable schema file per version (the IR's rule, ir/README.md). A
# version missing here is refused, never validated against a neighbour.
SCHEMAS = {0: "part-data.schema.json", 1: "part-data.v1.schema.json"}
# The bundled seed store: a record's path is its part_id, so lookup is one
# path and there is no index and no search.
STORE = Path(__file__).resolve().parent / "parts"
RECORD_SUFFIX = ".part.json"

ROLES = ("power_in", "power_out", "passive", "bidirectional", "open_drain",
         "open_collector", "tri_state", "input", "output", "nc")
# A record pin's role admits a definition role when they are equal, or when
# the record's role is one of these. A datasheet `passive` contact takes its
# function from the design (a connector's VBUS is power_out in the design and
# a plain contact in the receptacle's datasheet); a datasheet bidirectional
# pin can be narrowed by the design to any signal role. Anything else is a
# conflict: a wrong role silently disarms ERC, so it is never overridden.
ADMITS = {
    "passive": frozenset(ROLES),
    "bidirectional": frozenset(("bidirectional", "input", "output",
                                "tri_state", "open_drain", "open_collector")),
}
# Standard-library definitions that model one product, not a family: the
# definition IS that part's pinout, so it states each pin's role and the
# relation above does not apply. A record implementing one must carry the
# same role on every pin. Narrowing is for a generic definition (a
# connector, LinearRegulator), where the design says what a contact is for;
# on these, a role that differs from the record's is drift between the
# library and the datasheet, and it would silently disarm ERC. Add a
# definition here in the change that adds it to rhoform/lib.
PART_SPECIFIC = frozenset((
    "rhoform.lib.module.Esp32S3Wroom1",
    "rhoform.lib.regulator.Lm25145",
    "rhoform.lib.timer.Ne555",
))

STATISTICS = ("min", "typ", "max", "peak")
GUARANTEED = ("min", "max")
# Provenance confidences under which a min or max is the vendor's guarantee.
# `estimated` marks an in-house guardband and `unverified` an unchecked
# import; neither is a vendor guarantee, whatever slot the number sits in.
VENDOR_CONFIDENCE = ("datasheet-stated", "datasheet-derived",
                     "vendor-confirmed")

# The hosts each vendor publishes its documents from, by registrable domain:
# a source URL must be on its own vendor's list (L21). A distributor page may
# be used to FIND a document but never cited, and the schema's origin enum
# cannot see a distributor URL dressed as vendor-direct. Add a vendor here in
# the change that adds its first record.
VENDOR_DOMAINS = {
    "diodes": ("diodes.com",),
    "espressif": ("espressif.com",),
    "ti": ("ti.com",),
    "vishay": ("vishay.com",),
}

# Field families requirement R29a names (pin roles, abs-max,
# supply-current-per-mode), as pointer patterns where `*` is any one token.
# `not-transcribed` is a choice, not a fact about the part, so a record a
# benchmark picks may not use it on any of these, nor on anything covering
# one ("/ratings" hides "/ratings/abs_max" as surely as naming it).
R29A_FAMILIES = (("pins", "*", "role"), ("pins", "*", "abs_max"),
                 ("pin_classes", "*", "role"), ("pin_classes", "*", "abs_max"),
                 ("ratings", "abs_max"), ("modes",))


def touches_r29a(pointer):
    """True when `pointer` is inside an R29a family or covers one."""
    tokens = pointer.split("/")[1:]
    return any(all(want in ("*", have) for want, have in zip(family, tokens))
               for family in R29A_FAMILIES)


# Restrictiveness ordering for L10. Higher means more restrictive.
LICENSE_RANK = {"open-cc": 0, "vendor-public": 1, "vendor-agreement": 2}

# Arrays sorted by an identity member, which a pointer addresses by index.
INDEXED = ("implements", "pins", "modes", "sources", "pin_classes",
           "straps")


class Problem(NamedTuple):
    """One defect: the rule (a lint id L1-L22, "json", "version", "schema",
    or for a binding the join rule it breaks), where in the document (an
    RFC 6901 pointer), and why."""
    check: str
    pointer: str
    message: str


class PartDataError(Exception):
    """A record that cannot be trusted, with every reason found."""

    def __init__(self, path, problems):
        self.path = str(path)
        self.problems = tuple(problems)
        super().__init__(f"{path}: " + "; ".join(
            f"{p.check}: {p.message}" for p in self.problems))


# ---- reading ---------------------------------------------------------------

def _refuse_constant(token):
    raise ValueError(f"{token} is not a JSON number")


def _unique_pairs(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def _text(data: bytes) -> str:
    if not isinstance(data, bytes):
        raise TypeError("part records are read as bytes")
    return data.decode("utf-8")


# Deeper than any record a schema version describes (version 1 nests nine
# levels at most) and shallow enough for every recursive walk here. The
# decoder alone is no bound: it accepts nesting far past Python's stack, and
# where the layout, the schema or the lint then overflowed would depend on
# the caller's stack depth, so the same bytes could be refused for different
# reasons from different call sites.
MAX_NESTING = 32


def _unreadable(node):
    """Why a decoded document is not a record's JSON, or None. Walked with
    a stack, not recursion, because nothing has bounded its depth yet."""
    stack = [(node, 0)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, str):
            # The decoder joins a valid surrogate pair into one character, so
            # anything left in this range came from a lone `\ud800`-style
            # escape, which no UTF-8 byte sequence can spell back.
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in item):
                return ("a string in it holds a lone surrogate escape, which "
                        "UTF-8 cannot carry")
        elif isinstance(item, (dict, list)):
            if depth == MAX_NESTING:
                return f"it nests more than {MAX_NESTING} levels deep"
            children = [*item, *item.values()] if isinstance(item, dict) \
                else item
            stack.extend((child, depth + 1) for child in children)
    return None


def _decode(data: bytes, parse_float, parse_int):
    """One JSON document from `data`, or PartDataError with the reason.
    Refused: bad UTF-8, a duplicate key, NaN or Infinity, a lone surrogate,
    and nesting past MAX_NESTING. Each is a `json` problem, never an
    exception the caller has not been told about."""
    try:
        node = json.loads(_text(data), parse_float=parse_float,
                          parse_int=parse_int, parse_constant=_refuse_constant,
                          object_pairs_hook=_unique_pairs)
        reason = _unreadable(node)
        if reason is not None:
            raise ValueError(reason)
    except RecursionError:
        # The decoder's own limit, which some interpreters reach first. The
        # message is _unreadable's, so the reason does not depend on which
        # of the two noticed.
        raise PartDataError("<bytes>", [Problem(
            "json", "", f"it nests more than {MAX_NESTING} levels deep")]) \
            from None
    except (UnicodeDecodeError, ValueError) as exc:
        raise PartDataError("<bytes>", [Problem("json", "", str(exc))]) \
            from None
    return node


def parse(data: bytes):
    """The record in `data`, with exact numbers. Raises PartDataError."""
    return _decode(data, Decimal, int)


def revision(data: bytes) -> str:
    """The record's identity: sha256 over its exact file bytes."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _Number(str):
    """A JSON number token, kept exactly as written."""


def _layout(node, depth=0) -> str:
    """`json.dumps(indent=2, sort_keys=True, ensure_ascii=False)`, except
    that a number is written back as its own token rather than re-spelt."""
    pad = "  " * (depth + 1)
    if isinstance(node, _Number):
        return str(node)
    if isinstance(node, str):
        return json.dumps(node, ensure_ascii=False)
    if node is True or node is False or node is None:
        return json.dumps(node)
    if isinstance(node, list):
        if not node:
            return "[]"
        inner = ",\n".join(pad + _layout(item, depth + 1) for item in node)
        return "[\n" + inner + "\n" + "  " * depth + "]"
    if not node:
        return "{}"
    inner = ",\n".join(
        pad + json.dumps(key, ensure_ascii=False) + ": "
        + _layout(value, depth + 1) for key, value in sorted(node.items()))
    return "{\n" + inner + "\n" + "  " * depth + "}"


def canonical_layout(data: bytes) -> bytes:
    """The canonical bytes of the record in `data`. Raises PartDataError."""
    return (_layout(_decode(data, _Number, _Number)) + "\n").encode("utf-8")


def layout_problems(data: bytes) -> list:
    """L22: the record is in canonical layout, so its byte hash is a
    function of its content. Names the first line that differs."""
    try:
        canonical = canonical_layout(data)
    except PartDataError as exc:
        return list(exc.problems)
    if data == canonical:
        return []
    have, want = data.split(b"\n"), canonical.split(b"\n")
    line = next((i for i, (a, b) in enumerate(zip(have, want)) if a != b),
                min(len(have), len(want)))
    return [Problem("L22", "", (
        f"not in canonical layout (UTF-8, LF, two-space indent, sorted keys, "
        f"numbers as written, one trailing LF): line {line + 1} reads "
        f"{(have[line] if line < len(have) else b'<end of file>')!r}, "
        f"canonical is "
        f"{(want[line] if line < len(want) else b'<end of file>')!r}. The "
        "revision is the hash of these bytes, so a layout-only difference "
        "would be a different revision of the same facts."))]


# ---- schema ----------------------------------------------------------------

_VALIDATORS = {}


def _validator(version):
    """The validator for one schema version, read once. Raises ImportError
    when the pinned jsonschema is missing: an unavailable check, never a
    pass."""
    import jsonschema

    if version not in _VALIDATORS:
        path = SCHEMA_DIR / SCHEMAS[version]
        schema = json.loads(path.read_text(encoding="utf-8"))
        _VALIDATORS[version] = \
            jsonschema.validators.validator_for(schema)(schema)
    return _VALIDATORS[version]


def schema_version(doc):
    """The integer version `doc` declares, or None."""
    version = doc.get("schema_version") if isinstance(doc, dict) else None
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    return version


def validate(doc) -> list:
    """Shape: the schema of the version the record declares, and no other."""
    version = schema_version(doc)
    if version not in SCHEMAS:
        declared = doc.get("schema_version") if isinstance(doc, dict) else None
        return [Problem("version", "/schema_version", (
            f"declares schema_version {declared!r}; this toolchain implements "
            f"versions {', '.join(str(v) for v in sorted(SCHEMAS))} only, and "
            "a record of any other version is refused rather than read "
            "against a neighbouring version's schema"))]
    return [Problem("schema",
                    "".join(f"/{part}" for part in error.absolute_path),
                    error.message)
            for error in sorted(_validator(version).iter_errors(doc),
                                key=lambda e: (list(map(str, e.absolute_path)),
                                               e.message))]


# ---- pointers --------------------------------------------------------------

def unescape_token(token):
    """RFC 6901: ~1 is '/', ~0 is '~', and ~1 must be decoded first."""
    return token.replace("~1", "/").replace("~0", "~")


def pointer_resolves(doc, pointer):
    """True if an RFC 6901 pointer names an existing location in doc."""
    if pointer == "":
        return True
    if not pointer.startswith("/"):
        return False
    node = doc
    for raw in pointer.split("/")[1:]:
        token = unescape_token(raw)
        if isinstance(node, dict):
            if token not in node:
                return False
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit():
                return False
            index = int(token)
            if index >= len(node):
                return False
            node = node[index]
        else:
            return False
    return True


def pointer_target(doc, pointer):
    """Resolve a pointer and return the node, or None if it does not resolve."""
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        return None
    node = doc
    for raw in pointer.split("/")[1:]:
        token = unescape_token(raw)
        if isinstance(node, dict):
            if token not in node:
                return None
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                return None
            node = node[int(token)]
        else:
            return None
    return node


def identity_of(node):
    """The identity field of an addressable array element, if it has one."""
    if isinstance(node, dict):
        for key in ("id", "name", "source_id", "definition"):
            if key in node and isinstance(node[key], str):
                return node[key]
    return None


def covering(pointers, pointer):
    """The longest of `pointers` that is `pointer` or one of its prefixes."""
    best = None
    for candidate in pointers:
        if (candidate == "" or pointer == candidate
                or pointer.startswith(candidate + "/")):
            if best is None or len(candidate) > len(best):
                best = candidate
    return best


def _is_number(value):
    return isinstance(value, (int, float, Decimal)) \
        and not isinstance(value, bool)


def _is_measure(node):
    return isinstance(node, dict) and "unit" in node \
        and any(k in node for k in STATISTICS)


def walk_measures(node, path=""):
    """Yield (path, measure) for every object that looks like a Measure."""
    if isinstance(node, dict):
        if _is_measure(node):
            yield path, node
        for key, value in node.items():
            yield from walk_measures(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk_measures(value, f"{path}/{i}")


def condition_arrays(node, path=""):
    """Yield (path, array) for every array whose items are all Measures."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from condition_arrays(value, f"{path}/{key}")
    elif isinstance(node, list):
        if node and all(_is_measure(item) for item in node):
            yield path, node
        for i, value in enumerate(node):
            yield from condition_arrays(value, f"{path}/{i}")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      default=str)


# ---- pin classes -------------------------------------------------------------

BLOCKS = ("abs_max", "recommended", "capability", "characteristics")


def effective_pin(doc, pin):
    """`pin` with its class's blocks under its own, member by member."""
    classes = {c.get("id"): c for c in doc.get("pin_classes", [])
               if isinstance(c, dict)}
    pin_class = classes.get(pin.get("class"))
    if pin_class is None:
        return pin
    merged = dict(pin)
    for block in BLOCKS:
        if isinstance(pin_class.get(block), dict):
            merged[block] = {**pin_class[block], **(pin.get(block) or {})}
    return merged


# ---- the lint core -----------------------------------------------------------

def lint_problems(doc, unchecked=None, *, picked=False, domains=None):
    """Every cross-reference defect in one parsed record.

    `unchecked` collects checks that could not be PERFORMED on this record, as
    distinct from checks that failed. The two must not be conflated in either
    direction: reporting an unresolvable bound as a defect blames the record
    for a limitation of the data model, and skipping it silently -- which is
    what happened until AMB-123 -- leaves a containment gate covering some pins
    and not others with no way to tell which.

    `picked` marks a record a benchmark picks, on which `not-transcribed` is
    refused for the R29a field families (L18). `domains` replaces
    VENDOR_DOMAINS, for fixtures citing hosts no vendor owns.

    Checks (each is a real defect that shape validation would let through):

      L1  provenance keys resolve to a location that exists in the document.
      L2  every provenance source_id names a declared source.
      L3  source_id values are unique within the record.
      L4  modes[].draw[].pin names a declared pin whose role is power_in.
      L5  multi-unit consistency: unit pin membership exists, is disjoint from
          shared_pins, is disjoint between units, every pin's `unit` matches a
          declared unit, and on a multi-unit part every pin is accounted for.
      L6  shared_pins names declared pins.
      L7  pin names are unique, and no physical designator is claimed twice.
      L8  determinism: pins, modes, sources and draw entries are sorted.
      L9  Measure bounds are ordered: min <= typ <= max where all are numeric,
          and a peak is never below a guaranteed min.
      L10 the record's license_class is at least as restrictive as every
          source it cites.
      L11 a provenance pointer addressing an element of a SORTED array echoes
          that element's identity, so a re-sort cannot silently re-point it.
      L12 a pin's (effective) recommended window sits inside its
          absolute-maximum window.
      L13 physical designators are in ascending natural order.
      L14 implements: entries sorted and unique by definition; every map value
          and unbound pin is a declared record pin; the map is injective; no
          pin is both mapped and unbound; and every record pin is mapped,
          unbound, or nc. (Totality over the DEFINITION needs the definition:
          `bind` checks it.)
      L15 pin classes: sorted and unique by id; a pin's class exists; a member
          carries its class's role; every class has a member.
      L16 straps: sorted and unique by id; a combination names only pins that
          carry `strap`; no two combinations require the same levels.
      L17 a power_out pin carries no recommended voltage: what an output
          delivers is `output.voltage`, with its conditions.
      L18 absent: sorted and unique by pointer; the pointer does not resolve
          (no absence alongside a value) but its parent does; an indexed
          pointer echoes its element's identity; and on a picked record no
          R29a field is `not-transcribed`.
      L19 the Measures of a condition array state pairwise-distinct
          conditions.
      L20 reserved for the checker-reliable key vocabulary (landing L2d).
      L21 every source URL is on its vendor's host allowlist.
      L22 canonical layout -- a property of the bytes, so `layout_problems`.
    """
    problems = []
    unchecked = problems if unchecked is None else unchecked
    domains = VENDOR_DOMAINS if domains is None else domains

    def bad(check, pointer, message):
        problems.append(Problem(check, pointer, message))

    def cannot_check(check, pointer, message):
        unchecked.append(Problem(check, pointer, message))

    pins = doc.get("pins", [])
    pin_names = [p.get("name") for p in pins]
    pin_by_name = {p.get("name"): p for p in pins}
    sources = doc.get("sources", [])
    source_ids = [s.get("source_id") for s in sources]

    # L3 first: later checks reference source ids.
    if len(set(source_ids)) != len(source_ids):
        bad("L3", "/sources", "duplicate source_id values in sources[]")

    def echo(check, pointer, entry, what):
        """L11/L18: an indexed pointer into a sorted array names its element."""
        parts = pointer.split("/")
        if not (len(parts) >= 3 and parts[1] in INDEXED and parts[2].isdigit()):
            return
        actual = identity_of(pointer_target(doc, "/".join(parts[:3])))
        if actual is None:
            return
        declared = entry.get("target")
        if declared is None:
            bad(check, pointer,
                f"{what} {pointer!r} addresses {parts[1]}[{parts[2]}] by index "
                f"but declares no target; add \"target\": {actual!r} so a "
                "re-sort of the array cannot silently re-point this citation")
        elif declared != actual:
            bad(check, pointer,
                f"{what} {pointer!r} declares target {declared!r} but resolves "
                f"to {actual!r}; the array was reordered without updating the "
                "citation")

    # L1, L2, L11
    for pointer, entry in sorted(doc.get("provenance", {}).items()):
        if not pointer_resolves(doc, pointer):
            bad("L1", pointer, f"provenance pointer {pointer!r} does not "
                               "resolve to any location")
        sid = entry.get("source_id")
        if sid not in source_ids:
            bad("L2", pointer, f"provenance {pointer!r} cites unknown "
                               f"source_id {sid!r}")
        echo("L11", pointer, entry, "provenance")

    # L4
    for i, mode in enumerate(doc.get("modes", [])):
        for j, draw in enumerate(mode.get("draw", [])):
            pin_name = draw.get("pin")
            pin = pin_by_name.get(pin_name)
            if pin is None:
                bad("L4", f"/modes/{i}/draw/{j}/pin",
                    f"modes[{i}].draw[{j}] names unknown pin {pin_name!r}")
            elif pin.get("role") != "power_in":
                bad("L4", f"/modes/{i}/draw/{j}/pin",
                    f"modes[{i}].draw[{j}] attributes supply current to pin "
                    f"{pin_name!r} whose role is {pin.get('role')!r}, not "
                    "power_in")

    # L5, L6
    units = doc.get("units", [])
    shared = doc.get("shared_pins", [])
    for name in shared:
        if name not in pin_by_name:
            bad("L6", "/shared_pins", f"shared_pins names unknown pin {name!r}")

    if units:
        unit_ids = {u.get("id") for u in units}
        claimed = {}
        for u, unit in enumerate(units):
            for name in unit.get("pins", []):
                if name not in pin_by_name:
                    bad("L5", f"/units/{u}/pins",
                        f"unit {unit.get('id')!r} names unknown pin {name!r}")
                if name in shared:
                    bad("L5", f"/units/{u}/pins",
                        f"pin {name!r} is claimed by unit {unit.get('id')!r} "
                        "and also listed in shared_pins; a pin belongs to one "
                        "or the other")
                if name in claimed:
                    bad("L5", f"/units/{u}/pins",
                        f"pin {name!r} is claimed by both unit "
                        f"{claimed[name]!r} and unit {unit.get('id')!r}")
                claimed[name] = unit.get("id")
        for i, pin in enumerate(pins):
            name, declared = pin.get("name"), pin.get("unit")
            if declared is not None and declared not in unit_ids:
                bad("L5", f"/pins/{i}/unit",
                    f"pin {name!r} declares unit {declared!r}, which is not "
                    "in units[]")
            if declared is None and name not in shared:
                bad("L5", f"/pins/{i}",
                    f"pin {name!r} on a multi-unit part belongs to no unit and "
                    "is not in shared_pins; every pin must be accounted for")
            if declared is not None and claimed.get(name) != declared:
                bad("L5", f"/pins/{i}/unit",
                    f"pin {name!r} declares unit {declared!r} but that unit "
                    "does not list it as a member")
    else:
        for i, pin in enumerate(pins):
            if pin.get("unit") is not None:
                bad("L5", f"/pins/{i}/unit",
                    f"pin {pin.get('name')!r} declares a unit but units[] is "
                    "absent")

    # L7
    if len(set(pin_names)) != len(pin_names):
        bad("L7", "/pins", "duplicate pin names")
    seen_designators = {}
    for i, pin in enumerate(pins):
        for number in pin.get("numbers", []):
            if number in seen_designators:
                bad("L7", f"/pins/{i}/numbers",
                    f"physical designator {number!r} is claimed by both pin "
                    f"{seen_designators[number]!r} and pin {pin.get('name')!r}")
            seen_designators[number] = pin.get("name")

    # L8
    def check_sorted(values, pointer, what):
        if values != sorted(values):
            bad("L8", pointer, f"{what} are not sorted bytewise-ascending "
                               "(determinism contract)")

    check_sorted(pin_names, "/pins", "pins[].name")
    check_sorted([m.get("id") for m in doc.get("modes", [])], "/modes",
                 "modes[].id")
    check_sorted(source_ids, "/sources", "sources[].source_id")
    for i, mode in enumerate(doc.get("modes", [])):
        check_sorted([d.get("pin") for d in mode.get("draw", [])],
                     f"/modes/{i}/draw", f"modes[{i}].draw[].pin")

    # L9
    for path, measure in walk_measures(doc):
        ordered = [(key, measure[key]) for key in ("min", "typ", "max")
                   if _is_number(measure.get(key))]
        for (ka, va), (kb, vb) in zip(ordered, ordered[1:]):
            if va > vb:
                bad("L9", path, f"{path}: {ka}={va} exceeds {kb}={vb}")
        # `peak` sits outside the min/typ/max ordering because it is not a
        # guaranteed bound, but it still cannot fall below a guaranteed
        # minimum: an observed peak under the floor the vendor promises is
        # a transcription error, not a fact about the part.
        peak, lo = measure.get("peak"), measure.get("min")
        if _is_number(peak) and _is_number(lo) and peak < lo:
            bad("L9", path, f"{path}: peak={peak} is below the guaranteed "
                            f"min={lo}")

    # L12: a recommended window must sit inside its absolute-maximum window,
    # on the EFFECTIVE pin, so a window a class supplies is held too. A part
    # recommended to operate outside its own damage threshold is a defect in
    # the record, and no schema keyword can compare two sibling objects.
    for i, raw in enumerate(pins):
        pin = effective_pin(doc, raw)
        limits_abs = pin.get("abs_max") or {}
        limits_rec = pin.get("recommended") or {}
        where = f"/pins/{i}/recommended"
        for quantity in ("voltage", "current"):
            a, r = limits_abs.get(quantity), limits_rec.get(quantity)
            if isinstance(r, dict) and not isinstance(a, dict):
                # A recommended window with NO absolute maximum to contain it.
                # This was `continue`d silently, so the shipped AP7361C
                # accepted a recommended current of -1000 A on a 1 A part.
                # Same rule as the relative-bound case: reported, never
                # skipped.
                cannot_check("L12", f"{where}/{quantity}",
                             f"pin {pin.get('name')!r}: recommended "
                             f"{quantity} has no abs_max {quantity} to be "
                             "contained by, so nothing bounds it")
                continue
            if not (isinstance(a, dict) and isinstance(r, dict)):
                continue
            # Never compare across units. Millivolts against volts would
            # both false-positive on a legitimate record and, worse, miss
            # real over-stress by a factor of a thousand.
            if a.get("unit") != r.get("unit"):
                bad("L12", f"{where}/{quantity}",
                    f"pin {pin.get('name')!r}: recommended {quantity} is in "
                    f"{r.get('unit')!r} but abs_max is in {a.get('unit')!r}; "
                    "containment cannot be checked across units")
                continue
            a_lo, a_hi = a.get("min"), a.get("max")
            # A RelativeBound (`{reference, offset}`) is not a number. Resolving
            # the reference needs a supply value the record does not carry, so
            # it is REPORTED as unchecked rather than skipped: a containment
            # gate that quietly covers some pins and not others, with no way
            # to tell which, is the shape of gap this module exists to close.
            for endpoint, side in ((a_lo, "min"), (a_hi, "max")):
                if isinstance(endpoint, dict) and "reference" in endpoint:
                    cannot_check(
                        "L12", f"/pins/{i}/abs_max/{quantity}/{side}",
                        f"pin {pin.get('name')!r}: abs_max {quantity} "
                        f"{side} is a relative bound "
                        f"({endpoint.get('reference')}"
                        f"{endpoint.get('offset', 0):+g}), so containment "
                        "cannot be checked without a value for that "
                        "reference. Either state the bound numerically or "
                        "record the reference's value in the same record; "
                        "an unresolvable limit checks nothing.")
            for key in ("min", "typ", "max"):
                value = r.get(key)
                if not _is_number(value):
                    continue
                if _is_number(a_lo) and value < a_lo:
                    bad("L12", f"{where}/{quantity}/{key}",
                        f"pin {pin.get('name')!r}: recommended {quantity} "
                        f"{key}={value} is below abs_max min={a_lo}")
                if _is_number(a_hi) and value > a_hi:
                    bad("L12", f"{where}/{quantity}/{key}",
                        f"pin {pin.get('name')!r}: recommended {quantity} "
                        f"{key}={value} exceeds abs_max max={a_hi}")

    # L13: physical designators are documented as sorted ascending, for the
    # same determinism reason as every other ordering here.
    for i, pin in enumerate(pins):
        numbers = pin.get("numbers", [])
        if numbers != sorted(numbers, key=lambda n: (len(str(n)), str(n))):
            bad("L13", f"/pins/{i}/numbers",
                f"pin {pin.get('name')!r}: numbers {numbers} are not in "
                "ascending order (natural sort: shorter designators first, "
                "then bytewise)")

    # L10
    record_rank = LICENSE_RANK.get(doc.get("license_class"))
    if record_rank is not None:
        for s, source in enumerate(sources):
            source_rank = LICENSE_RANK.get(source.get("license_class"))
            if source_rank is not None and source_rank > record_rank:
                bad("L10", f"/sources/{s}/license_class",
                    f"source {source.get('source_id')!r} is licensed "
                    f"{source.get('license_class')!r}, which is more "
                    f"restrictive than the record's {doc.get('license_class')!r}")

    # L14: the join. A map that misses a pin, or lands two definition pins on
    # one record pin, binds a design to a part it does not describe.
    implements = doc.get("implements", [])
    definitions = [e.get("definition") for e in implements]
    if definitions != sorted(set(definitions)):
        bad("L14", "/implements", "implements[] must be sorted bytewise-"
                                  "ascending by definition, one entry each")
    for e, entry in enumerate(implements):
        where = f"/implements/{e}"
        mapping = entry.get("pins", {})
        unbound = entry.get("unbound", [])
        landed = {}
        for def_pin, record_pin in sorted(mapping.items()):
            if record_pin not in pin_by_name:
                bad("L14", f"{where}/pins/{def_pin}",
                    f"{entry.get('definition')}: definition pin {def_pin!r} "
                    f"maps to {record_pin!r}, which is not a pin of this "
                    "record")
            if record_pin in landed:
                bad("L14", f"{where}/pins/{def_pin}",
                    f"{entry.get('definition')}: definition pins "
                    f"{landed[record_pin]!r} and {def_pin!r} both map to "
                    f"record pin {record_pin!r}; the map must be injective, "
                    "or two design ports silently share one terminal")
            landed.setdefault(record_pin, def_pin)
        if unbound != sorted(unbound):
            bad("L14", f"{where}/unbound",
                f"{entry.get('definition')}: unbound[] is not sorted "
                "bytewise-ascending")
        for name in unbound:
            if name not in pin_by_name:
                bad("L14", f"{where}/unbound",
                    f"{entry.get('definition')}: unbound names {name!r}, "
                    "which is not a pin of this record")
            if name in landed:
                bad("L14", f"{where}/unbound",
                    f"{entry.get('definition')}: record pin {name!r} is both "
                    "mapped and listed as unbound")
        for pin in pins:
            name = pin.get("name")
            if name not in landed and name not in unbound \
                    and pin.get("role") != "nc":
                bad("L14", f"{where}/pins",
                    f"{entry.get('definition')}: record pin {name!r} is "
                    "neither mapped, listed as unbound, nor of role nc, so "
                    "nothing says whether the definition omits it on purpose")

    # L15: pin classes share data; they never re-type a pin.
    pin_classes = doc.get("pin_classes", [])
    class_ids = [c.get("id") for c in pin_classes]
    if class_ids != sorted(set(class_ids)):
        bad("L15", "/pin_classes", "pin_classes[] must be sorted bytewise-"
                                   "ascending by id, each id once")
    class_by_id = {c.get("id"): c for c in pin_classes}
    members = set()
    for i, pin in enumerate(pins):
        if "class" not in pin:
            continue
        pin_class = class_by_id.get(pin["class"])
        if pin_class is None:
            bad("L15", f"/pins/{i}/class",
                f"pin {pin.get('name')!r} names pin class {pin['class']!r}, "
                "which pin_classes[] does not declare, so the data it was "
                "meant to inherit is silently missing")
            continue
        members.add(pin["class"])
        if pin.get("role") != pin_class.get("role"):
            bad("L15", f"/pins/{i}/role",
                f"pin {pin.get('name')!r} has role {pin.get('role')!r} but "
                f"its class {pin['class']!r} declares {pin_class.get('role')!r}; "
                "a class shares data, it never re-types a pin")
    for c, pin_class in enumerate(pin_classes):
        if pin_class.get("id") not in members:
            bad("L15", f"/pin_classes/{c}",
                f"pin class {pin_class.get('id')!r} has no member pin")

    # L16: strapping. A combination naming a pin with no strap data cannot be
    # evaluated, and two rows requiring the same levels contradict each other.
    straps = doc.get("straps", [])
    strap_ids = [s.get("id") for s in straps]
    if strap_ids != sorted(set(strap_ids)):
        bad("L16", "/straps", "straps[] must be sorted bytewise-ascending by "
                              "id, each id once")
    seen_when = {}
    for s, combination in enumerate(straps):
        when = combination.get("when", {})
        for name in sorted(when):
            if "strap" not in (pin_by_name.get(name) or {}):
                bad("L16", f"/straps/{s}/when/{name}",
                    f"strap combination {combination.get('id')!r} needs pin "
                    f"{name!r} at a level, but that pin "
                    f"{'carries no strap block' if name in pin_by_name else 'does not exist'}")
        key = _canonical(when)
        if key in seen_when:
            bad("L16", f"/straps/{s}/when",
                f"strap combinations {seen_when[key]!r} and "
                f"{combination.get('id')!r} require the same levels")
        seen_when.setdefault(key, combination.get("id"))

    # L17: an output's accuracy is a fact about what the part produces, at the
    # conditions it was stated under. As a `recommended` window it read as an
    # all-conditions window the design must hold the pin inside.
    for i, raw in enumerate(pins):
        pin = effective_pin(doc, raw)
        if pin.get("role") == "power_out" and \
                "voltage" in (pin.get("recommended") or {}):
            bad("L17", f"/pins/{i}/recommended/voltage",
                f"pin {pin.get('name')!r} is power_out and carries a "
                "recommended voltage; what an output delivers is "
                "output.voltage, with the conditions it holds under")

    # L18: an absence is a statement, so it gets the same rigour as a value.
    absent = doc.get("absent", [])
    absent_pointers = [a.get("pointer") for a in absent]
    if absent_pointers != sorted(set(absent_pointers)):
        bad("L18", "/absent", "absent[] must be sorted bytewise-ascending by "
                              "pointer, each pointer once")
    for entry in absent:
        pointer = entry.get("pointer", "")
        parent = pointer.rsplit("/", 1)[0]
        if pointer_resolves(doc, pointer):
            bad("L18", pointer,
                f"{pointer!r} is declared absent "
                f"({entry.get('reason')}) and also carries a value; one of "
                "the two is wrong")
        elif not pointer_resolves(doc, parent):
            bad("L18", pointer,
                f"absent {pointer!r}: its parent {parent or '/'!r} does not "
                "resolve, so the absence names no field of this record")
        echo("L18", pointer, entry, "absent")
        if picked and entry.get("reason") == "not-transcribed" \
                and touches_r29a(pointer):
            bad("L18", pointer,
                f"absent {pointer!r} is not-transcribed on a record a "
                "benchmark picks; pin roles, abs-max and supply-current-per-"
                "mode are required data there (R29a), and a vendor value that "
                "exists must be transcribed")

    # L19: a condition array is several operating points of one quantity. Two
    # elements at the same conditions are one point stated twice, and a
    # consumer selecting by conditions could take either.
    for path, array in condition_arrays(doc):
        seen = {}
        for k, measure in enumerate(array):
            key = _canonical(measure.get("conditions"))
            if key in seen:
                bad("L19", f"{path}/{k}/conditions",
                    f"{path}: elements {seen[key]} and {k} state the same "
                    "conditions; each element of a condition array is a "
                    "distinct operating point")
            seen.setdefault(key, k)

    # L21: provenance has to be the vendor's own document.
    for s, source in enumerate(sources):
        vendor = source.get("vendor")
        try:
            host = (urlsplit(source.get("url", "")).hostname or "").lower()
        except ValueError:
            host = ""
        allowed = domains.get(vendor)
        if allowed is None:
            bad("L21", f"/sources/{s}/vendor",
                f"source {source.get('source_id')!r}: vendor {vendor!r} has "
                "no host allowlist, so nothing shows its URL is the vendor's "
                "own; add the vendor's domains to VENDOR_DOMAINS")
        elif not any(host == d or host.endswith("." + d) for d in allowed):
            bad("L21", f"/sources/{s}/url",
                f"source {source.get('source_id')!r}: {host!r} is not one of "
                f"{vendor}'s hosts ({', '.join(allowed)}); a distributor or "
                "mirror page may help find a document but is never cited")

    return problems


def lint(doc, label, unchecked=None, **options):
    """lint_problems() as `<label>: <check>: <message>` lines, the form
    parts/lint-part-data.py prints."""
    raw = None if unchecked is None else []
    found = lint_problems(doc, raw, **options)
    if unchecked is not None:
        unchecked.extend(f"{label}: {p.check}: {p.message}" for p in raw)
    return [f"{label}: {p.check}: {p.message}" for p in found]


# ---- loading -----------------------------------------------------------------

@dataclass(frozen=True)
class Record:
    """A record that parsed, is in canonical layout, validated against its
    version's schema and linted clean."""
    path: str
    revision: str
    document: dict
    unchecked: tuple

    @property
    def part_id(self):
        return self.document["part_id"]

    @property
    def schema_version(self):
        return self.document["schema_version"]


def check(data: bytes, *, picked=False):
    """(parsed record, problems, unchecked) for one record's bytes. Raises
    ImportError when jsonschema is missing."""
    try:
        doc = parse(data)
    except PartDataError as exc:
        return None, list(exc.problems), []
    problems = layout_problems(data)
    problems += validate(doc)
    unchecked = []
    if not any(p.check in ("version", "schema") for p in problems):
        problems += lint_problems(doc, unchecked, picked=picked)
    return doc, problems, unchecked


def load(path, *, picked=False) -> Record:
    """Read one record from `path` and refuse it unless it can be trusted.
    Raises PartDataError, OSError, or ImportError (jsonschema missing)."""
    data = Path(path).read_bytes()
    doc, problems, unchecked = check(data, picked=picked)
    if problems:
        raise PartDataError(path, problems)
    return Record(str(path), revision(data), doc, tuple(unchecked))


def store_path(part_id: str) -> Path:
    """Where the bundled store keeps `part_id`: the path IS the identity."""
    vendor, slug = part_id.split("/")
    return STORE / vendor / (slug + RECORD_SUFFIX)


# ---- binding -----------------------------------------------------------------

@dataclass(frozen=True)
class Relative:
    """`factor * V(reference) + offset`, left symbolic for the checker."""
    reference: str
    factor: Decimal
    offset: Decimal


@dataclass(frozen=True)
class Value:
    """One published statistic. `guaranteed` is True only for a min or max
    whose provenance is the vendor's (VENDOR_CONFIDENCE); a typ or a peak
    never is."""
    statistic: str
    bound: object
    guaranteed: bool


@dataclass(frozen=True)
class Measure:
    """One Measure as published: where it was read, its unit, its statistics,
    the conditions it holds under, and the confidence of its provenance."""
    pointer: str
    unit: str
    values: tuple
    conditions: dict
    confidence: str

    def get(self, statistic):
        return next((v for v in self.values if v.statistic == statistic), None)

    @property
    def guaranteed(self):
        return tuple(v for v in self.values if v.guaranteed)


@dataclass(frozen=True)
class PinFacts:
    """What the record says about the record pin one definition pin lands on,
    with any class data folded in. Every measured value is a tuple of Measures:
    one, or one per published operating point."""
    pin: str
    role: str
    numbers: tuple
    pin_class: object
    abs_max: dict
    recommended: dict
    capability: dict
    characteristics: dict
    output: dict
    strap: object
    absent: dict


@dataclass(frozen=True)
class Binding:
    """A record joined to one definition: facts per definition pin, and the
    part-level data, with every value statistic-tagged."""
    definition: str
    part_id: str
    ports: dict
    unbound: tuple
    modes: tuple
    parameters: dict
    ratings: dict
    series: dict
    straps: tuple
    absent: dict
    problems: tuple


def compatible(record_role, definition_role, *, exact=False):
    """True when a record pin of `record_role` may carry a design port of
    `definition_role` (see ADMITS). With `exact`, as for a PART_SPECIFIC
    definition, only the same role may."""
    return record_role == definition_role or (
        not exact and definition_role in ADMITS.get(record_role, ()))


def _bound(raw):
    if isinstance(raw, dict):
        return Relative(raw["reference"], Decimal(raw.get("factor", 1)),
                        Decimal(raw.get("offset", 0)))
    return raw


def _measures(doc, node, pointer):
    """The Measure, or each Measure of a condition array, at `pointer`."""
    provenance = doc.get("provenance", {})
    items = node if isinstance(node, list) else [node]
    found = []
    for k, item in enumerate(items):
        where = f"{pointer}/{k}" if isinstance(node, list) else pointer
        key = covering(provenance, where)
        confidence = provenance[key]["confidence"] if key is not None \
            else "unsourced"
        values = tuple(
            Value(stat, _bound(item[stat]),
                  stat in GUARANTEED and confidence in VENDOR_CONFIDENCE)
            for stat in STATISTICS if stat in item)
        found.append(Measure(where, item["unit"], values,
                             dict(item.get("conditions") or {}), confidence))
    return tuple(found)


def _block(doc, block, pointer, class_block=None, class_pointer=None):
    """{member: Measures} for one named-measure block, a class's under the
    pin's own, each Measure pointing at the place it was read from."""
    out = {}
    for source, where in ((class_block, class_pointer), (block, pointer)):
        for name, node in sorted((source or {}).items()):
            out[name] = _measures(doc, node, f"{where}/{name}")
    return out


def _absences(doc):
    return {a["pointer"]: a["reason"] for a in doc.get("absent", [])}


def _pin_facts(doc, index, absences):
    pin = doc["pins"][index]
    classes = doc.get("pin_classes", [])
    c = next((k for k, entry in enumerate(classes)
              if entry.get("id") == pin.get("class")), None)
    pin_class = classes[c] if c is not None else {}
    here, there = f"/pins/{index}", f"/pin_classes/{c}"
    blocks = {name: _block(doc, pin.get(name), f"{here}/{name}",
                           pin_class.get(name), f"{there}/{name}")
              for name in BLOCKS}
    absent = {}
    for pointer, reason in sorted(absences.items()):
        for root in ((here, there) if c is not None else (here,)):
            if pointer.startswith(root + "/"):
                field = pointer[len(root) + 1:]
                # A pin's own value overrides its class's absence.
                if root == there and pointer_resolves(
                        pin, "/" + field):
                    continue
                absent[field] = reason
    return PinFacts(
        pin=pin["name"], role=pin["role"], numbers=tuple(pin["numbers"]),
        pin_class=pin.get("class"), abs_max=blocks["abs_max"],
        recommended=blocks["recommended"], capability=blocks["capability"],
        characteristics=blocks["characteristics"],
        output=_block(doc, pin.get("output"), f"{here}/output"),
        strap=pin.get("strap"), absent=absent)


def bind(record, definition, pins) -> Binding:
    """Join `record` to `definition` through its `implements` map.

    `record` is a Record or a parsed document. `pins` is the definition's
    pins, as (name, role, designators) triples. The binding's `problems`
    name every pin the join cannot account for and every role the record
    cannot carry; the caller decides what each one costs. A pin that does
    not join gets no facts: an unjoined port has no data, which is different
    from a joined port whose record states nothing."""
    doc = record.document if isinstance(record, Record) else record
    problems = []
    pins = [(name, role, tuple(numbers)) for name, role, numbers in pins]
    entry = next((e for e in doc.get("implements", [])
                  if e.get("definition") == definition), None)
    exact = definition in PART_SPECIFIC
    absences = _absences(doc)
    ports, unbound = {}, ()
    if entry is None:
        problems.append(Problem(
            "no-implements", "/implements",
            f"{doc.get('part_id')} implements no {definition}; its pins "
            "cannot be joined to that definition's ports without guessing"))
    else:
        mapping = entry.get("pins", {})
        unbound = tuple(entry.get("unbound", ()))
        index = {p["name"]: i for i, p in enumerate(doc.get("pins", []))}
        names = {name for name, _role, _numbers in pins}
        for extra in sorted(set(mapping) - names):
            problems.append(Problem(
                "pin-unknown", f"/implements/{doc['implements'].index(entry)}"
                f"/pins/{extra}",
                f"{doc.get('part_id')} maps {definition} pin {extra!r}, "
                "which the definition does not declare"))
        for name, role, numbers in sorted(pins):
            record_pin = mapping.get(name)
            if record_pin not in index:
                problems.append(Problem(
                    "pin-unmapped", "/implements",
                    f"{doc.get('part_id')}: {definition} pin {name!r} lands "
                    "on no record pin"))
                continue
            facts = _pin_facts(doc, index[record_pin], absences)
            if not compatible(facts.role, role, exact=exact):
                problems.append(Problem(
                    "role-conflict", f"/pins/{index[record_pin]}/role",
                    f"{doc.get('part_id')}: {definition} pin {name!r} is "
                    f"{role}, and record pin {record_pin!r} is "
                    f"{facts.role}, " + (
                        "which cannot carry it"
                        if not compatible(facts.role, role) else
                        f"and {definition} models one part, so its roles "
                        "must equal the record's")))
            if numbers and tuple(sorted(numbers, key=lambda n: (len(n), n))) \
                    != facts.numbers:
                problems.append(Problem(
                    "designator-mismatch", f"/pins/{index[record_pin]}/numbers",
                    f"{doc.get('part_id')}: {definition} pin {name!r} sits on "
                    f"designators {list(numbers)}, record pin {record_pin!r} "
                    f"on {list(facts.numbers)}"))
            ports[name] = facts
    reverse = {} if entry is None else {
        record_pin: name for name, record_pin in entry.get("pins", {}).items()}
    modes = tuple(
        (mode["id"], mode["kind"], dict(mode.get("conditions") or {}),
         {reverse.get(draw["pin"], draw["pin"]): _measures(
             doc, draw["current"], f"/modes/{m}/draw/{d}/current")[0]
          for d, draw in enumerate(mode["draw"])})
        for m, mode in enumerate(doc.get("modes", [])))
    ratings = {kind: _block(doc, block, f"/ratings/{kind}")
               for kind, block in sorted((doc.get("ratings") or {}).items())}
    return Binding(
        definition=definition, part_id=doc.get("part_id"), ports=ports,
        unbound=unbound, modes=modes,
        parameters=_block(doc, doc.get("parameters"), "/parameters"),
        ratings=ratings,
        series=_block(doc, doc.get("series"), "/series"),
        straps=tuple(doc.get("straps", ())), absent=absences,
        problems=tuple(problems))
