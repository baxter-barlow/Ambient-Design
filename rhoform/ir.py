"""IR v2 emission: an ElaboratedDesign to the netlist IR and its source map.

This module owns three things the elaborator deliberately does not:

  - THE ENCODER. `rhoform-canonical-json/1` as ir/README.md defines it and
    tests/ir/check-hashes.py implements it: UTF-8, keys sorted by code
    point, no insignificant whitespace, literal non-ASCII, no lone
    surrogates, no NaN/Infinity, arrays in order, and numbers spelled by
    ECMA-262 Number::toString. It is written out here rather than
    imported, because the gate is a hyphenated script under tests/ and the
    package must not depend on it; rhoform/tests/test_ir.py loads the gate
    by path and holds the two to byte equality instead.
  - THE ONE DECIMAL-TO-DOUBLE STEP. The elaborated design is exact; an IR
    number is the IEEE-754 double nearest the exact decimal (round half
    to even), which is what `float(Decimal)` computes. The IR is
    inspectable, not authoritative (P7), so this is where exactness ends.
  - THE HASHES. `design_hash` is sha256 over the canonical bytes with
    `design_hash`, `generator` and `source_hash` blanked (the gate's
    rule). `source_hash` is sha256 over the canonical bytes of the list
    of `[path, sha256_hex]` pairs for every source file read, sorted by
    path, which is the serialization the gate reported as unpinned.

Every array is emitted in the order the schema declares, so one design has
one serialization and therefore one hash.

VERSION 2 (ir/netlist-ir.v2.schema.json), UNFROZEN until M2 exit (decision
OD8; ir/README.md, "Unfrozen working versions"). It carries the source facts
syntax 0.3 adds and the one IR v1 dropped: an `isolated` net, a net's
authored `ground_kind`, a component's `rules`, an assertion's `severity`,
the `annotations` (`supply`, `draw`, `waive`), and an `interfaces` array that
syntax 0.3's interfaces fill (empty until then). It drops
Assertion.waiver, which nothing wrote: a waiver is an annotation now. With
those removed and `ir_version` 1, a version 2 document is the version 1
document of the same design (rhoform/tests/test_ir_v2.py holds that).
"""

from decimal import Decimal
import hashlib
import json

from .elaborate import Quantity

CANONICAL_PROFILE = "rhoform-canonical-json/1"
# Version 2 (ir/netlist-ir.v2.schema.json, ir/source-map.v2.schema.json),
# unfrozen; version 1 widened net names, version 2 adds the 0.3 source facts
# (ir/README.md, "Versioning policy").
IR_VERSION = 2
SOURCEMAP_VERSION = 2
GENERATOR = {"name": "rhoformc", "version": "0.1.0-dev"}
NON_DESIGN_HEADER_FIELDS = ("design_hash", "generator", "source_hash")


# ---- rhoform-canonical-json/1 ---------------------------------------------

def canonical_number(value) -> str:
    """Clause 7: ECMA-262 Number::toString over the value as a double."""
    if isinstance(value, bool):
        raise TypeError("booleans are not numbers")
    if isinstance(value, int):
        try:
            as_float = float(value)
        except OverflowError:
            as_float = float("inf")
        if as_float in (float("inf"), float("-inf")) \
                or int(as_float) != value:
            raise ValueError(
                f"{value} is not exactly representable as an IEEE double; "
                "integers beyond 2^53 are rejected, not rounded (clause 7)")
        value = as_float
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("NaN and Infinity are not representable")
    if value == 0:
        return "0"
    sign, digits, exponent = Decimal(repr(value)).as_tuple()
    n = exponent + len(digits)
    s = "".join(str(digit) for digit in digits).rstrip("0") or "0"
    k = len(s)
    if k <= n <= 21:
        text = s + "0" * (n - k)
    elif 0 < n <= 21:
        text = s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * (-n) + s
    else:
        mantissa = s if k == 1 else s[0] + "." + s[1:]
        power = n - 1
        text = f"{mantissa}e{'+' if power >= 0 else '-'}{abs(power)}"
    return "-" + text if sign else text


def _canonical_str(value: str) -> str:
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise ValueError("lone surrogates are not representable in "
                         "rhoform-canonical-json/1 (clause 4)")
    return json.dumps(value, ensure_ascii=False)


def _encode(node) -> str:
    if node is None:
        return "null"
    if isinstance(node, bool):
        return "true" if node else "false"
    if isinstance(node, (int, float)):
        return canonical_number(node)
    if isinstance(node, str):
        return _canonical_str(node)
    if isinstance(node, list):
        return "[" + ",".join(_encode(item) for item in node) + "]"
    if isinstance(node, dict):
        return "{" + ",".join(
            _canonical_str(key) + ":" + _encode(value)
            for key, value in sorted(node.items())) + "}"
    raise TypeError(f"{type(node).__name__} is not representable in JSON")


def canonical_bytes(document) -> bytes:
    """Serialize per rhoform-canonical-json/1, with its one trailing LF."""
    return _encode(document).encode("utf-8") + b"\n"


def design_hash_of(document: dict) -> str:
    blanked = dict(document)
    blanked["header"] = dict(document["header"])
    for name in NON_DESIGN_HEADER_FIELDS:
        if name in blanked["header"]:
            blanked["header"][name] = ""
    return "sha256:" + hashlib.sha256(canonical_bytes(blanked)).hexdigest()


def source_hash_of(files) -> str:
    """`files`: (path, sha256 hex) pairs for every source read."""
    pairs = sorted([path, digest] for path, digest in files)
    return "sha256:" + hashlib.sha256(canonical_bytes(pairs)).hexdigest()


# ---- the IR document --------------------------------------------------------

def number(value: Decimal) -> float:
    """The IEEE double nearest an exact decimal (round half to even)."""
    return float(value)


def _value(value):
    if isinstance(value, Quantity):
        out = {"value": number(value.value), "unit": value.unit}
        if value.tolerance is not None:
            low, high = value.tolerance
            out["tolerance"] = {"min": number(low), "max": number(high)}
        return out
    return value  # str, bool or int, carried as is


def _instance(instance) -> dict:
    out = {
        "path": instance.path,
        "kind": instance.kind,
        "definition": instance.definition,
        "parameters": {name: _value(value)
                       for name, value in instance.parameters.items()},
        "ports": [],
        "dnp": instance.dnp,
        "exclude_from_bom": instance.exclude_from_bom,
        "board_only": instance.board_only,
    }
    for port in sorted(instance.ports, key=lambda p: p.name):
        entry = {"name": port.name, "role": port.role}
        if port.pin_numbers:
            entry["pin_numbers"] = sorted(port.pin_numbers)
        out["ports"].append(entry)
    if instance.hardware_kind is not None:
        out["hardware_kind"] = instance.hardware_kind
    if instance.rules:
        out["rules"] = _by_bytes(_rule(rule) for rule in instance.rules)
    part = instance.part
    if part is not None:
        constraints = {name: _value(value)
                       for name, value in part.constraints.items()}
        if part.binding == "abstract":
            out["part"] = {"binding": "abstract", "constraints": constraints}
        else:
            out["part"] = {"binding": "resolved",
                           "lockfile_key": part.lockfile_key}
            if constraints:
                out["part"]["constraints"] = constraints
    return out


def _by_bytes(entries) -> list:
    """Entries of a list whose order carries no meaning, in the order of
    their canonical bytes: total, so one set has one serialization."""
    return sorted(entries, key=canonical_bytes)


def _rule(rule) -> dict:
    out = {"word": rule.word, "pins": list(rule.pins)}
    if rule.side is not None:
        out["name"] = rule.side
    if rule.relation is not None:
        out[rule.relation] = rule.other
    if rule.value is not None:
        out["value"] = _value(rule.value)
    return out


def _net(net) -> dict:
    out = {"name": net.name}
    if net.ground_domain is not None:
        out["ground_domain"] = net.ground_domain
    if net.voltage_domain is not None:
        out["voltage_domain"] = net.voltage_domain
    if net.ground_kind is not None:
        out["ground_kind"] = net.ground_kind
    if net.isolated:
        out["isolated"] = True
    return out


def _bounds(bounds) -> dict:
    out = {"unit": bounds.unit}
    if bounds.min is not None:
        out["min"] = number(bounds.min)
    if bounds.max is not None:
        out["max"] = number(bounds.max)
    return out


def _assertion(assertion) -> dict:
    out = {
        "path": assertion.path,
        "tier": assertion.tier,
        "measurement": assertion.measurement,
        "subject": {"net": assertion.subject},
        "bounds": _bounds(assertion.bounds),
    }
    if assertion.severity == "warning":
        out["severity"] = "warning"
    return out


def _target(target) -> dict:
    kind, *what = target
    if kind == "port":
        return {"port": {"instance": what[0], "port": what[1]}}
    return {kind: what[0]}


def _annotation(annotation) -> dict:
    out = {"kind": annotation.kind, "scope": annotation.scope,
           "target": _target(annotation.target)}
    if annotation.kind == "waive":
        out["code"] = annotation.code
        out["justification"] = annotation.justification
    else:
        out["bounds"] = _bounds(annotation.bounds)
    return out


def to_ir(design) -> dict:
    """The IR v2 document, hashes filled in."""
    document = {
        "header": {
            "ir_version": IR_VERSION,
            "language_version": design.language_version,
            "design_name": design.design_name,
            "design_hash": "",
            "source_hash": source_hash_of(
                (f.path, f.sha256) for f in design.files),
            "generator": dict(GENERATOR),
            "canonical_form": CANONICAL_PROFILE,
        },
        "instances": [_instance(i)
                      for i in sorted(design.instances, key=lambda i: i.path)],
        "nets": [_net(n) for n in sorted(design.nets, key=lambda n: n.name)],
        "connections": [
            {"net": net, "port": {"instance": path, "port": port}}
            for net, path, port in design.connections()],
        "assertions": [_assertion(a) for a in
                       sorted(design.assertions, key=lambda a: a.path)],
        # Syntax 0.3's interfaces fill this; nothing does yet.
        "interfaces": [],
        "annotations": _by_bytes(_annotation(a) for a in design.annotations),
    }
    document["header"]["design_hash"] = design_hash_of(document)
    return document


# ---- the source map ---------------------------------------------------------

def to_source_map(design, design_hash: str) -> dict:
    files = sorted(design.files, key=lambda f: f.path)
    index = {f.path: position for position, f in enumerate(files)}

    def span(raw) -> dict:
        return {
            "file": index[raw.file],
            "byte_start": raw.byte_start,
            "byte_end": raw.byte_end,
            "line_start": raw.line_start,
            "col_start": raw.col_start,
            "line_end": raw.line_end,
            "col_end": raw.col_end,
        }

    nodes = {}
    for entity, declaration, trace in (
            [(i.path, i.declaration, i.trace) for i in design.instances]
            + [(n.name, n.declaration, n.trace) for n in design.nets]
            + [(a.path, a.declaration, a.trace) for a in design.assertions]):
        nodes[entity] = {
            "declaration": span(declaration),
            "instantiation_trace": [span(s) for s in trace],
        }
    return {
        "sourcemap_version": SOURCEMAP_VERSION,
        "ir_version": IR_VERSION,
        "design_hash": design_hash,
        "files": [{"path": f.path, "sha256": f.sha256} for f in files],
        "nodes": nodes,
    }


def emit(design) -> tuple[bytes, bytes]:
    """(IR bytes, source-map bytes), both canonical."""
    document = to_ir(design)
    source_map = to_source_map(design, document["header"]["design_hash"])
    return canonical_bytes(document), canonical_bytes(source_map)
