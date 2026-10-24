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
    holds it to the cross-references no JSON Schema can state (L1-L23,
    listed at `lint_problems`), including the checker-reliable key
    vocabulary (`VOCABULARY`, L20): the keys a check may read out of the
    schema's open maps, each with its dimension. parts/lint-part-data.py is
    a thin gate over these functions.
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
    Its `reference` is always a RECORD pin name (L23), never a design name,
    and the binding re-keys ports and leaves references alone, so a checker
    reaches the referenced port through `Binding.port_of(reference)`.

HERMETIC. partdata opens the path it is given and, once per process per
schema_version, the toolchain's own schema file for that version
(parts/part-data[.vN].schema.json); it lists nothing, starts no process, and
opens no network connection.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
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
# D3's part_id, `<vendor-slug>/<part-slug>`, exactly as both schema versions
# spell it (rhoform/tests/test_partdata.py holds the three equal). Each slug
# starts and ends with a letter or digit and the vendor's holds no dot, so an
# id this admits cannot be `..`, absolute, or carry a second separator: the
# store path it names is always one directory under STORE.
PART_ID = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?/"
                     r"[a-z0-9]([a-z0-9._-]{0,61}[a-z0-9])?(?![\s\S])")

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
# the change that adds its first record. Each key is the vendor slug that
# also starts the vendor's part_ids, and each domain is one the vendor itself
# operates: Murata serves its per-part specifications from murata.co.jp,
# TDK serves EPCOS film capacitors from tdk-electronics.tdk.com, and
# Kingbright's US subsidiary serves the catalogue PDFs from kingbrightusa.com.
VENDOR_DOMAINS = {
    "ck": ("ckswitches.com",),
    "coilcraft": ("coilcraft.com",),
    "diodes": ("diodes.com",),
    "espressif": ("espressif.com",),
    "gct": ("gct.co",),
    "infineon": ("infineon.com",),
    "kemet": ("kemet.com",),
    "keystone": ("keyelco.com",),
    "kingbright": ("kingbright.com", "kingbrightusa.com"),
    "littelfuse": ("littelfuse.com",),
    "murata": ("murata.com", "murata.co.jp"),
    "st": ("st.com",),
    "sullins": ("sullinscorp.com",),
    "tdk": ("tdk.com",),
    "ti": ("ti.com",),
    "vishay": ("vishay.com",),
    "yageo": ("yageo.com",),
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


# ---- L20: the checker-reliable key vocabulary -----------------------------
#
# `parameters`, `ratings.*` and `characteristics` are open maps, because
# their vocabulary is part-family specific; so a key in one is a name nobody
# promised to read. These are the keys a check MAY read. Each has one home
# (the section it is listed under) and one dimension, and L20 holds every
# Measure under one to that dimension. Any other key stays legal and no
# check reads it, so a misspelling costs coverage, never a wrong verdict. A
# dimension is a quantities.DIMENSIONS name, `dimensionless`, a ratio `a/b`
# of two of them, `temperature` (a reading on the degC scale: `K` is a
# difference and is refused there) or a level (`dB`, `dBm`). What each key
# means is parts/README.md, "Checker-reliable keys"; the meaning is part of
# the contract, so a key is added there in the change that adds it here.
VOCABULARY = {
    # What the part IS: its defining values, as the vendor states them.
    "parameters": {
        "breakdown_voltage": "voltage",
        "capacitance": "capacitance",
        "capacitance_dc_bias_change": "dimensionless",
        "capacitance_tolerance": "dimensionless",
        "clamping_voltage": "voltage",
        "efficiency": "dimensionless",
        "gate_threshold_voltage": "voltage",
        "hold_current": "current",
        "impedance": "resistance",
        "inductance": "inductance",
        "inductance_tolerance": "dimensionless",
        "rds_on": "resistance",
        "reference_voltage": "voltage",
        "resistance": "resistance",
        "resistance_tolerance": "dimensionless",
        "reverse_leakage_current": "current",
        "temperature_characteristic": "dimensionless",
        "temperature_coefficient": "dimensionless/temperature",
        "trip_current": "current",
    },
    # Stress limits: the vendor's absolute-maximum table. Exceeding one is
    # damage.
    "ratings/abs_max": {
        "drain_current": "current",
        "esd_cdm": "voltage",
        "esd_hbm": "voltage",
        "esd_iec_air": "voltage",
        "esd_iec_contact": "voltage",
        "esd_mm": "voltage",
        "forward_current": "current",
        "interrupt_current": "current",
        "junction_temperature": "temperature",
        "overload_voltage": "voltage",
        "peak_forward_current": "current",
        "peak_pulse_current": "current",
        "peak_pulse_power": "power",
        "power_dissipation": "power",
        "pulsed_drain_current": "current",
        "storage_temperature": "temperature",
        "surge_current": "current",
    },
    # Operating ratings: what the design must keep the part within. A
    # two-terminal rating is across the part's two terminals.
    "ratings/recommended": {
        "ambient_temperature": "temperature",
        "current_rating": "current",
        "power_rating": "power",
        "rms_current": "current",
        "saturation_current": "current",
        "voltage_rating": "voltage",
    },
    "ratings/thermal": {
        "psi_jb": "temperature/power",
        "psi_jt": "temperature/power",
        "theta_ja": "temperature/power",
        "theta_jb": "temperature/power",
        "theta_jc": "temperature/power",
        "theta_jc_bottom": "temperature/power",
        "theta_jc_top": "temperature/power",
        "theta_jl": "temperature/power",
    },
    # On a pin, or on a pin class for its members.
    "characteristics": {
        "capacitance": "capacitance",
        "input_current": "current",
        "leakage_current": "current",
        "pull_down_resistance": "resistance",
        "pull_up_resistance": "resistance",
        "required_supply_current": "current",
        "vih": "voltage",
        "vil": "voltage",
        "voh": "voltage",
        "vol": "voltage",
    },
}
# A characteristic only one pin role can carry: what a supply must be able to
# deliver INTO a pin is a fact about a power_in pin and nothing else.
ROLE_BOUND_CHARACTERISTICS = {"required_supply_current": "power_in"}
# The schema's closed slots, which have one dimension by construction.
CLOSED_DIMENSIONS = {
    ("abs_max", "current"): "current",
    ("abs_max", "voltage"): "voltage",
    ("capability", "sink_current"): "current",
    ("capability", "source_current"): "current",
    ("output", "current_limit"): "current",
    ("output", "dropout"): "voltage",
    ("output", "voltage"): "voltage",
    ("recommended", "current"): "current",
    ("recommended", "voltage"): "voltage",
    ("series", "forward_voltage"): "voltage",
    ("series", "resistance"): "resistance",
    ("draw", "current"): "current",
}
# Condition names with one meaning, so a check can select an operating point
# by them (`ta` is the ambient, as a reading). A string condition is legal
# under any name; a numeric one under a name listed here has its dimension.
CONDITION_DIMENSIONS = {
    "cin": "capacitance", "cload": "capacitance", "cout": "capacitance",
    "cpu_frequency": "frequency", "duration": "time",
    "duty_cycle": "dimensionless", "frequency": "frequency",
    "id": "current", "if": "current", "iin": "current", "iol": "current",
    "ioh": "current", "iout": "current", "ipp": "current", "ir": "current",
    "it": "current", "pulse_width": "time", "rload": "resistance",
    "ta": "temperature", "tc": "temperature", "tj": "temperature",
    "tx_power": "dBm", "vcc": "voltage", "vdc": "voltage", "vdd": "voltage",
    "vds": "voltage", "vgs": "voltage", "vin": "voltage", "voh": "voltage",
    "vol": "voltage", "vout": "voltage", "vr": "voltage",
}


def vocabulary_slot(pointer):
    """(where, key, dimension spec) for the Measure at `pointer` when a
    check may read it, else None. `where` names the vocabulary it is held
    to: a VOCABULARY section, `closed`, or `conditions`."""
    tokens = pointer.split("/")[1:]
    if "conditions" in tokens:
        rest = tokens[len(tokens) - tokens[::-1].index("conditions"):]
        name = rest[0] if rest else None
        spec = CONDITION_DIMENSIONS.get(name)
        return None if spec is None else ("conditions", name, spec)
    head = tokens[0] if tokens else None
    if head == "parameters" and len(tokens) > 1:
        section, key = "parameters", tokens[1]
    elif head == "ratings" and len(tokens) > 2:
        section, key = f"ratings/{tokens[1]}", tokens[2]
    elif head == "series" and len(tokens) > 1:
        spec = CLOSED_DIMENSIONS.get(("series", tokens[1]))
        return None if spec is None else ("closed", tokens[1], spec)
    elif head == "modes" and len(tokens) > 4 and tokens[2] == "draw":
        return ("closed", "current", CLOSED_DIMENSIONS[("draw", "current")]) \
            if tokens[4] == "current" else None
    elif head in ("pins", "pin_classes") and len(tokens) > 3:
        block, key = tokens[2], tokens[3]
        if block == "characteristics":
            section = "characteristics"
        else:
            spec = CLOSED_DIMENSIONS.get((block, key))
            return None if spec is None else ("closed", key, spec)
    else:
        return None
    spec = VOCABULARY.get(section, {}).get(key)
    return None if spec is None else (section, key, spec)


# Restrictiveness ordering for L10. Higher means more restrictive.
LICENSE_RANK = {"open-cc": 0, "vendor-public": 1, "vendor-agreement": 2}

# Arrays sorted by an identity member, which a pointer addresses by index.
INDEXED = ("implements", "pins", "modes", "sources", "pin_classes",
           "straps")


class Problem(NamedTuple):
    """One defect: the rule (a lint id L1-L22, "json", "version", "schema",
    "part_id" for an id no store path can name, or for a binding the join
    rule it breaks), where in the document (an RFC 6901 pointer), and why."""
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


def _integral(value):
    """True for an exact number with no fractional part, as JSON Schema
    defines an integer: `3` and `3.0` alike. jsonschema's own rule knows
    int and float; partdata parses a fraction as a Decimal, which it does
    not, so `"pin_count": 3.0` passed the schema gate (which reads floats)
    and was refused here. One rule for both readers."""
    return isinstance(value, Decimal) and value.is_finite() \
        and value == value.to_integral_value()


def _validator(version):
    """The validator for one schema version, read once. Raises ImportError
    when the pinned jsonschema is missing: an unavailable check, never a
    pass."""
    import jsonschema

    if version not in _VALIDATORS:
        path = SCHEMA_DIR / SCHEMAS[version]
        schema = json.loads(path.read_text(encoding="utf-8"))
        base = jsonschema.validators.validator_for(schema)
        checker = base.TYPE_CHECKER.redefine(
            "integer", lambda checker, value: _integral(value)
            or base.TYPE_CHECKER.is_type(value, "integer"))
        _VALIDATORS[version] = jsonschema.validators.extend(
            base, type_checker=checker)(schema)
    return _VALIDATORS[version]


def schema_version(doc):
    """The integer version `doc` declares, or None. `1.0` is version 1,
    as it is to the schema's `const`."""
    version = doc.get("schema_version") if isinstance(doc, dict) else None
    if _integral(version):
        return int(version)
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


def _exact(number):
    # Fraction reads a Decimal exactly; a float, which no parsed record
    # holds, exactly as its binary value.
    return Fraction(number)


def _affine(bound):
    """(reference, factor, offset) of a Bound: a number is the constant
    function, (None, 0, value). None for anything else."""
    if isinstance(bound, dict) and isinstance(bound.get("reference"), str):
        factor, offset = bound.get("factor", 1), bound.get("offset", 0)
        if _is_number(factor) and _is_number(offset):
            return bound["reference"], _exact(factor), _exact(offset)
        return None
    if _is_number(bound):
        return None, Fraction(0), _exact(bound)
    return None


def _difference(a, b):
    """a - b, exactly, when the two Bounds are the same function of the
    same reference; None when only a value for it could compare them."""
    fa, fb = _affine(a), _affine(b)
    if fa is None or fb is None or fa[:2] != fb[:2]:
        return None
    return fa[2] - fb[2]


def _show(bound):
    if isinstance(bound, dict):
        factor, offset = bound.get("factor", 1), bound.get("offset", 0)
        if not (_is_number(factor) and _is_number(offset)):
            return _canonical(bound)
        scaled = bound.get("reference") if factor == 1 \
            else f"{factor} x {bound.get('reference')}"
        return scaled if offset == 0 else \
            f"{scaled} {'-' if offset < 0 else '+'} {abs(offset)}"
    return str(bound)


def _condition_value(node):
    """One condition as a value: a Measure becomes its dimension, kind and
    each statistic in base units, exactly, so 5 V and 5.0 V and 5000 mV are
    one condition. A string, a relative bound or a unit the grammar cannot
    read is left as written (L20 reports the unit)."""
    if not _is_measure(node):
        return ("as-written", _canonical(node))
    try:
        unit = _values.parse_part_unit(node["unit"])
    except (_values.UnitError, TypeError):
        return ("as-written", _canonical(node))
    published = [stat for stat in STATISTICS if node.get(stat) is not None]
    if not all(_is_number(node[stat]) for stat in published):
        return ("as-written", _canonical(node))
    return ("measure", unit.dimension.exponents, unit.dimension.level,
            unit.kind, tuple((stat, _exact(node[stat]) * unit.scale)
                             for stat in published))


def condition_key(conditions):
    """A hashable value for a conditions map, compared by value (L16 and L19
    used to compare spellings, so `5` and `5.0` were two operating points)."""
    if not isinstance(conditions, dict):
        return ("as-written", _canonical(conditions))
    return tuple(sorted((name, _condition_value(value))
                        for name, value in conditions.items()))


def _strap_key(when):
    """A strap combination's levels by value: `x` is any level, which is
    what leaving a pin out also says."""
    if not isinstance(when, dict):
        return _canonical(when)
    return _canonical({pin: level for pin, level in when.items()
                       if level != "x"})


def _dimension(spec):
    """(Dimension, unit kind) a vocabulary dimension spec names."""
    if spec in ("dB", "dBm"):
        return _values.Dimension((0, 0, 0, 0, 0), spec), "level"
    if spec == "temperature":
        return _values.named("temperature"), "offset"
    if "/" in spec:
        top, bottom = spec.split("/")
        return _values.named(top) / _values.named(bottom), "linear"
    return _values.named(spec), "linear"


def _spell(dimension, kind):
    if kind == "offset":
        return "a temperature reading (degC)"
    return dimension.describe()


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
          absolute-maximum window. Two bounds are compared when both are
          numbers or both are relative to the same pin by the same factor
          (BST - SW against BST - SW); any other pair is unperformable.
      L13 physical designators are in ascending natural order.
      L14 implements: entries sorted and unique by definition; every map value
          and unbound pin is a declared record pin; the map is injective; no
          pin is both mapped and unbound; and every record pin is mapped,
          unbound, or nc. (Totality over the DEFINITION needs the definition:
          `bind` checks it.)
      L15 pin classes: sorted and unique by id; a pin's class exists; a member
          carries its class's role; every class has a member.
      L16 straps: sorted and unique by id; a combination names only pins that
          carry `strap`; no two combinations require the same levels, `x`
          and leaving a pin out both meaning any level.
      L17 a power_out pin carries no recommended voltage: what an output
          delivers is `output.voltage`, with its conditions.
      L18 absent: sorted and unique by pointer; the pointer does not resolve
          (no absence alongside a value), neither on the record nor through
          the pin's class (no absence alongside a value the class
          supplies), but its parent does; an indexed pointer echoes its
          element's identity; and on a picked record no R29a field is
          `not-transcribed`.
      L19 the Measures of a condition array state pairwise-distinct
          conditions, compared by value (`condition_key`), not spelling.
      L20 every Measure's unit is in the part-unit grammar
          (rhoform.check.values.parse_part_unit); a Measure in a closed slot,
          under a VOCABULARY key or under a CONDITION_DIMENSIONS condition
          has that slot's dimension; and a role-bound characteristic sits
          on a pin of its role.
      L21 every source URL is on its vendor's host allowlist.
      L22 canonical layout -- a property of the bytes, so `layout_problems`.
      L23 a relative bound names a pin of this record, and bounds a voltage.
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
            # A RelativeBound (`{reference, offset}`) is not a number, and two
            # bounds compare only when they are the same affine function of
            # the same pin (both numbers, or `BST + 14` against `BST + 6`).
            # Any other pair needs a value for the reference the record does
            # not carry, so it is REPORTED as unchecked rather than skipped:
            # a containment gate that quietly covers some pins and not
            # others, with no way to tell which, is the shape of gap this
            # module exists to close. A relative RECOMMENDED value against a
            # numeric limit used to be skipped in exactly that silent way.
            unresolved = {}
            for key in ("min", "typ", "max"):
                value = r.get(key)
                if value is None:
                    continue
                for endpoint, side in ((a_lo, "min"), (a_hi, "max")):
                    if endpoint is None:
                        continue
                    gap = _difference(value, endpoint)
                    if gap is None:
                        unresolved.setdefault(side, endpoint)
                    elif side == "min" and gap < 0:
                        bad("L12", f"{where}/{quantity}/{key}",
                            f"pin {pin.get('name')!r}: recommended {quantity} "
                            f"{key}={_show(value)} is below abs_max "
                            f"min={_show(a_lo)}")
                    elif side == "max" and gap > 0:
                        bad("L12", f"{where}/{quantity}/{key}",
                            f"pin {pin.get('name')!r}: recommended {quantity} "
                            f"{key}={_show(value)} exceeds abs_max "
                            f"max={_show(a_hi)}")
            for side, endpoint in sorted(unresolved.items()):
                cannot_check(
                    "L12", f"/pins/{i}/abs_max/{quantity}/{side}",
                    f"pin {pin.get('name')!r}: abs_max {quantity} {side} "
                    f"({_show(endpoint)}) and the recommended window are not "
                    "the same function of one reference (a relative bound "
                    "against a number, or against another reference), so "
                    "containment cannot be checked without a value for that "
                    "reference. State both numerically or both relative to "
                    "the same pin; an unresolvable limit checks nothing.")

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
        key = _strap_key(when)
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
        tokens = pointer.split("/")
        member = pointer_target(doc, "/".join(tokens[:3])) \
            if len(tokens) > 3 and tokens[1] == "pins" and tokens[3] in BLOCKS \
            else None
        if pointer_resolves(doc, pointer):
            bad("L18", pointer,
                f"{pointer!r} is declared absent "
                f"({entry.get('reason')}) and also carries a value; one of "
                "the two is wrong")
        elif isinstance(member, dict) and member.get("class") is not None \
                and pointer_resolves(effective_pin(doc, member),
                                     "/" + "/".join(tokens[3:])):
            # The binding hands a member its class's blocks, so this field
            # reached a checker as a value AND as an absence.
            bad("L18", pointer,
                f"{pointer!r} is declared absent "
                f"({entry.get('reason')}) on pin {member.get('name')!r}, but "
                f"its class {member.get('class')!r} supplies that field; a "
                "member cannot both inherit a value and lack it")
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
            key = condition_key(measure.get("conditions"))
            if key in seen:
                bad("L19", f"{path}/{k}/conditions",
                    f"{path}: elements {seen[key]} and {k} state the same "
                    "conditions; each element of a condition array is a "
                    "distinct operating point")
            seen.setdefault(key, k)

    # L20: a number is only as good as its unit. Every Measure's unit is read
    # by the grammar a check reads it with, and a Measure a check may read
    # (a closed slot, a vocabulary key, a named condition) has that slot's
    # dimension, so `voltage_rating` in mA or a `ta` in K is refused here
    # rather than met by a DimensionError, or a wrong verdict, in a pass.
    for path, measure in walk_measures(doc):
        try:
            unit = _values.parse_part_unit(measure.get("unit"))
        except (_values.UnitError, AttributeError) as exc:
            bad("L20", f"{path}/unit",
                f"{path}: unit {measure.get('unit')!r} is outside the "
                f"part-unit grammar, so no check can read its numbers: {exc}")
            continue
        slot = vocabulary_slot(path)
        if slot is None:
            continue
        where, key, spec = slot
        want, kind = _dimension(spec)
        if unit.dimension != want or unit.kind != kind:
            bad("L20", f"{path}/unit",
                f"{path}: {key!r} ({where}) is {_spell(want, kind)}, and "
                f"{measure.get('unit')!r} is "
                f"{_spell(unit.dimension, unit.kind)}")
    for collection in ("pins", "pin_classes"):
        for i, owner in enumerate(doc.get(collection, [])):
            for key in sorted(owner.get("characteristics") or {}):
                role = ROLE_BOUND_CHARACTERISTICS.get(key)
                if role is not None and owner.get("role") != role:
                    bad("L20", f"/{collection}/{i}/characteristics/{key}",
                        f"{key!r} on {owner.get('name', owner.get('id'))!r}, "
                        f"whose role is {owner.get('role')!r}: it states what "
                        f"a supply must deliver into a {role} pin, and a "
                        "check reads it nowhere else")

    # L23: a relative bound is factor x V(reference) + offset, where the
    # reference is a pin of THIS record. bind() re-keys ports by definition
    # pin and leaves references alone, so a reference to anything else (a
    # rail, a design net, a misspelt pin) is one no checker can resolve.
    for path, measure in walk_measures(doc):
        for stat in STATISTICS:
            bound = measure.get(stat)
            if not isinstance(bound, dict):
                continue
            reference = bound.get("reference")
            if reference not in pin_by_name:
                bad("L23", f"{path}/{stat}/reference",
                    f"{path}: {stat} is relative to {reference!r}, which is "
                    "not a pin of this record; a relative bound names the "
                    "record pin whose voltage it moves with")
                continue
            try:
                unit = _values.parse_part_unit(measure.get("unit"))
            except (_values.UnitError, AttributeError):
                continue
            if unit.dimension != _values.named("voltage") \
                    or unit.kind != "linear":
                bad("L23", f"{path}/{stat}",
                    f"{path}: {stat} is relative to pin {reference!r}'s "
                    f"voltage, and the Measure is "
                    f"{_spell(unit.dimension, unit.kind)}")

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
        return schema_version(self.document)


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
    """Where the bundled store keeps `part_id`: the path IS the identity.

    Raises PartDataError for anything that is not a D3 part_id. Splitting
    first resolved `../x` to a file beside the store and died with a bare
    ValueError on `a/../../b`; an id is checked before it becomes a path."""
    if not isinstance(part_id, str) or PART_ID.match(part_id) is None:
        raise PartDataError("<part_id>", [Problem(
            "part_id", "/part_id",
            f"{part_id!r} is not a D3 part_id (<vendor-slug>/<part-slug>, "
            "lower-case slugs), so it names no record in the store")])
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
    part-level data, with every value statistic-tagged.

    Ports and mode draws are keyed by DEFINITION pin. A Relative's
    `reference` stays a RECORD pin name (L23 holds it to one), because a
    bound is a fact about the part. `record_pins` maps each joined record
    pin to the definition pin it carries, so a checker resolves a reference
    with `port_of` and evaluates it in that port's net; a reference to a
    record pin the definition does not carry (one listed `unbound`)
    resolves to None, a bound no net can evaluate, which is a coverage row."""
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
    record_pins: dict

    def port_of(self, record_pin):
        """The definition pin `record_pin` is joined to, or None."""
        return self.record_pins.get(record_pin)


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
        problems=tuple(problems),
        record_pins={facts.pin: name for name, facts in ports.items()})


# Last, because rhoform.check.values imports Relative from this module: by
# here every name it needs exists, whichever of the two is imported first.
# The lint core reads units with the checker's own grammar (L20), so a unit
# the lint admits is one every pass can read.
from .check import values as _values  # noqa: E402
