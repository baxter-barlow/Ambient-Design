"""Part picks and records (L2b, AMB-59): pass 1, and the check context.

Spec 05/09 is normative; this says how the code reads it.

THE CONTEXT. `load_context` builds the CheckContext of one compilation:
its compile root and the rhoform.lock the package layer read and checked
there (rhoform/lockfile.py), or None. That is all the stage reads besides
the design, except the records the picks this design uses name, which
this pass opens, one read each, with the part-data schema of the version
each declares (rhoform/partdata.py). No MPN is searched and nothing is
fetched (D1).

THE PASS, per component instance in path order:

  - `part "key"` takes the keyed pick of that key. There must be one, with
    no lockfile too (decision D30): RHO6001 otherwise.
  - `part abstract` takes the instance pick of its design and identity
    path when there is one (decision D29); with none the part is
    unlocked, which is no defect -- D1's ladder begins there -- and the
    instance's facts are its constraints alone.
  - A component with no part statement, L9 hardware and a `tie` component
    (D1-exempt, amendment spec-fidelity 5) have nothing to verify.

A pick's record is located (spelled exactly, never through a link out of
the compile root; a `rhoform/` path is the toolchain's part store), read,
and its bytes' sha256 compared with the revision the lockfile records
(RHO6003, RHO6004); then its version, layout, schema and lint (RHO6005,
RHO6006); its identity against the pick's echoes (RHO6007); its join to the
instance's definition, through its `implements` map alone (RHO6008,
RHO6009). An instance pick is then held to the constraints the instance
states now: the digest it was made for (RHO6011, a stale pick) and the
constraint-satisfaction subset (RHO6010) -- mpn, manufacturer and package
equal the record's, a nominal's interval holds what the record guarantees,
and a rating or limit is met by the record's guaranteed maximum. A
constraint the subset does not cover, or whose record data cannot decide
it, is an actionable row: the pick is not shown to satisfy it.

L21, the vendor-host allowlist, is the bundled store's provenance policy,
so it holds records under `rhoform/parts/` and not a compile root's own,
whose provenance is their author's (AMB-151 item 12). Every other lint
clause holds every record.

The pass sets `analysis.parts` (PartsAnalysis): `facts(instance)` is what a
later pass may read about an instance's part, and `require` is how it
says it needed facts that are not there, which is a coverage row of its
own, never a silent pass.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field

from .. import lockfile
from .. import partdata
from ..codeset.parts import CODES
from ..diagnostics import Edit, FixIt
from ..elaborate import Quantity
from . import values

NAME = "parts"
OWNER = "parts"
IMPLEMENTED = True

# The coverage rows the pass writes, as (status, reason, kind). A failing
# pick's finding carries its own diagnostic, so its row is not actionable;
# an instance pick the subset could not show satisfies a constraint is.
# Spec 05/09 restates the table.
ROWS = (
    ("pass", "bound", "inherent"),
    ("no-data", "no-pick", "inherent"),
    ("no-data", "no-part-statement", "inherent"),
    ("not-run", "hardware", "inherent"),
    ("not-run", "net-tie", "inherent"),
    ("not-run", "record-check-unperformed", "inherent"),
    ("not-run", "constraint-ill-typed", "inherent"),
    ("not-run", "constraint-outside-subset", "actionable"),
    ("undecided", "constraint-unverified", "actionable"),
) + tuple(("fail", entry.slug, "inherent") for entry in CODES)

# The rows `require` writes into the section of the pass that calls it.
REQUIRE_ROWS = (
    ("no-data", "part-data-unresolved", "actionable"),
    ("no-data", "upstream-defect", "inherent"),
)

# The constraint names the subset compares with a record string: the
# constraint's name, and where in the record its value is.
EQUALITIES = (("manufacturer", ("manufacturer",)), ("mpn", ("mpn",)),
              ("package", ("package", "name")))


def code_rows() -> tuple:
    """(code, slug, severity) for every code of the pass's owner."""
    return tuple((entry.code, entry.slug, entry.severity) for entry in CODES)


# ---- the context ------------------------------------------------------------

# rhoform.check.check receives the CheckContext but hands a pass only
# (model, analysis, report), so the context reaches this pass here:
# load_context leaves it with the files of the compilation it was built
# for, and run() takes it, once, for the design elaborated from exactly
# those files. A design checked with no context built for it is checked
# unlocked. The route goes when the driver passes the context itself.
_BOUND: ContextVar = ContextVar("rhoform_check_parts_context",
                                default=None)


def _authored(files) -> frozenset:
    """(path, bytes) of a compilation's author files: no library module."""
    return frozenset((path, data) for path, data in files
                     if not path.startswith("rhoform/lib/"))


def load_context(root, compilation):
    """The CheckContext of one compilation (`compilation` is the package
    layer's): its compile root and its checked lockfile, or None."""
    from . import CheckContext

    context = CheckContext(root=root, lockfile=compilation.lockfile,
                           parts=partdata.STORE)
    _BOUND.set((_authored((result.file, result.data)
                          for result in compilation.results), context))
    return context


def _context(model):
    bound = _BOUND.get()
    _BOUND.set(None)
    if bound is not None and bound[0] == _authored(
            (f.path, f.data) for f in model.design.files):
        return bound[1]
    return None


# ---- what later passes read -------------------------------------------------

@dataclass(frozen=True)
class PartFacts:
    """What the pass concluded about one instance's part. `source` is `d3`
    for a verified pick, whose record `binding` joins the definition
    (rhoform.partdata.Binding), or `constraints` for an unlocked
    `part abstract`, known by its constraints alone."""

    source: str
    constraints: dict
    binding: object = None
    part_id: str | None = None
    revision: str | None = None
    record: str | None = None


@dataclass
class PartsAnalysis:
    """The facts of every instance with a part, by path, and the paths
    whose pick a finding reported, which later passes treat as unknown."""

    report: object
    found: dict = field(default_factory=dict)
    defects: set = field(default_factory=set)

    def facts(self, instance: str):
        """The PartFacts of an instance, or None: no part statement, or a
        pick the pass reported."""
        return self.found.get(instance)

    def require(self, instance: str, field: str, section: str):
        """A later pass needs part data `field` of `instance`: the verified
        facts, when there are some. Otherwise it records why not as a row of
        its own section `section` -- actionable when the part is simply
        unresolved, an `upstream-defect` when this pass reported its pick
        -- and returns what there is (an unlocked part's constraints, or
        None)."""
        if self.report.section != section:
            raise AssertionError(
                f"{section} requires part data while {self.report.section} "
                "is the open section; a pass records rows in its own")
        facts = self.found.get(instance)
        if facts is not None and facts.source == "d3":
            return facts
        if instance in self.defects:
            self.report.row(instance, "no-data", "upstream-defect",
                            detail={"field": field})
        else:
            self.report.row(instance, "no-data", "part-data-unresolved",
                            actionable=True, detail={"field": field})
        return facts


# ---- records ----------------------------------------------------------------

@dataclass(frozen=True)
class _Verdict:
    """A record as one pick reads it: its parsed document and the checks
    no record of its data supports, or the finding that refuses it (code,
    params, the lockfile pointer it spans, its fix-its)."""

    document: dict | None = None
    unchecked: tuple = ()
    code: str | None = None
    params: dict | None = None
    pointer: str | None = None
    fixits: tuple = ()


class _Records:
    """Each record a pick names, read and verified once per revision."""

    def __init__(self, root, lock):
        self.root = root
        self.lock = lock
        self.seen = {}

    def verdict(self, pick) -> _Verdict:
        key = (pick.record, pick.revision)
        if key not in self.seen:
            self.seen[key] = self._verify(pick)
        return self.seen[key]

    def _verify(self, pick) -> _Verdict:
        from ..package import ReadFailure

        entry = pick.pointer + "/record"
        where, problem = lockfile.locate(self.root, pick.record)
        if where is None:
            return _Verdict(code="RHO6003", params={
                "record": pick.record, "reason": problem}, pointer=entry)
        try:
            data = where.read_bytes()
        except OSError as exc:
            raise ReadFailure(where, exc) from None
        actual = lockfile.digest(data)
        if actual != pick.revision:
            pointer = self.lock.input_pointer("parts", pick.record) \
                + "/sha256"
            span = self.lock.span(pointer)
            return _Verdict(
                code="RHO6004",
                params={"record": pick.record, "recorded": pick.revision,
                        "actual": actual},
                pointer=pointer,
                fixits=(FixIt("re-pin the pick to the record as it is now",
                              "needs-review",
                              (Edit(span, f'"{actual}"'),)),))
        document, problems, unchecked = partdata.check(data)
        if not pick.record.startswith(lockfile.STORE_PREFIX):
            problems = [p for p in problems if p.check != "L21"]
        if any(p.check == "version" for p in problems):
            declared = "missing" if "schema_version" not in document \
                else lockfile.shown(document["schema_version"])
            return _Verdict(code="RHO6005", params={
                "record": pick.record, "version": declared,
                "supported": ", ".join(str(v) for v in
                                       sorted(partdata.SCHEMAS))},
                pointer=entry)
        if problems:
            return _Verdict(code="RHO6006", params={
                "record": pick.record,
                "problems": [f"{p.check} at {p.pointer or '/'}: "
                             + (NOT_JSON if p.check == "json" else p.message)
                             for p in problems]}, pointer=entry)
        return _Verdict(document=document, unchecked=tuple(
            f"{p.check} at {p.pointer or '/'}" for p in unchecked))


# ---- the pass ---------------------------------------------------------------

def _echoes(pick, document) -> list:
    """(field, the pick's echo, the record's value) for each that differs."""
    return [(name, getattr(pick, name), document.get(name))
            for name in ("part_id", "manufacturer", "mpn")
            if document.get(name) != getattr(pick, name)]


def _record_value(document, path):
    node = document
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _spelled(value) -> str:
    """A constraint value as a diagnostic shows it."""
    if isinstance(value, Quantity):
        low, high = values.display(values.from_quantity(value))
        return low if low == high else f"{low} to {high}"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _subset(part, binding, document):
    """D29's subset over one instance pick: (unsatisfied as (name,
    required, found), unverified names, names outside the subset, names
    of the wrong type)."""
    from .dimensions import CONSTRAINT_VOCABULARY

    unsatisfied, unverified, outside, ill_typed = [], [], [], []
    equal = dict(EQUALITIES)
    for name in sorted(part.constraints):
        value = part.constraints[name]
        if name in equal:
            stated = _record_value(document, equal[name])
            if stated != value:
                unsatisfied.append((name, _spelled(value),
                                    "nothing" if stated is None
                                    else _spelled(stated)))
            continue
        known = CONSTRAINT_VOCABULARY.get(name)
        if known is None:
            outside.append(name)
            continue
        dimension, kind = known
        if not isinstance(value, Quantity) or \
                values.from_quantity(value).dim != values.named(dimension):
            ill_typed.append(name)
            continue
        want = values.from_quantity(value)
        measures = binding.parameters.get(name, ())
        if len(measures) != 1:
            unverified.append(name)
            continue
        try:
            have = values.from_measure(measures[0])
        except (values.UnitError, KeyError, ValueError):
            unverified.append(name)
            continue
        if not isinstance(have, values.Q):
            unverified.append(name)
            continue
        if have.dim != want.dim or have.offset != want.offset:
            unsatisfied.append((name, _spelled(value),
                                f"a {have.dim.describe()}"))
            continue
        shown = values.display(have)
        found = f"{shown[0]} to {shown[1]}"
        if kind == "nominal":
            if not have.iv.bounded:
                unverified.append(name)
            elif values.relate(have, want) != "inside":
                unsatisfied.append((name, _spelled(value), found))
        elif values.POS_INF == have.iv.hi:
            unverified.append(name)
        elif (kind == "at_least" and have.iv.hi < want.iv.hi) or \
                (kind == "at_most" and have.iv.hi > want.iv.lo):
            unsatisfied.append((name, _spelled(value),
                                f"at most {shown[1]}"))
    return unsatisfied, unverified, outside, ill_typed


class _Pass:
    def __init__(self, model, analysis, report, context):
        self.model = model
        self.report = report
        self.root = None if context is None else context.root
        self.lock = None if context is None else context.lockfile
        self.records = _Records(self.root, self.lock)
        self.analysis = analysis.parts = PartsAnalysis(report)
        self.design = model.instances["/"].definition

    def fail(self, path, code, params, *, primary=None, secondary=(),
             fixits=(), detail=None):
        self.report.finding(code, params, entity=path, primary=primary,
                            secondary=secondary, fixits=fixits)
        slug = next(entry.slug for entry in CODES if entry.code == code)
        self.report.row(path, "fail", slug, detail=detail)
        self.analysis.defects.add(path)

    def run(self):
        picked = {}
        if self.lock is not None:
            for pick in self.lock.instance_picks(self.design):
                if self._names_abstract(pick):
                    picked[pick.instance] = pick
        for path in self.model.components:
            instance = self.model.instances[path]
            part = instance.part
            if part is None:
                if instance.hardware_kind is not None:
                    self.report.row(path, "not-run", "hardware")
                elif any(rule.word == "tie" for rule in instance.rules):
                    self.report.row(path, "not-run", "net-tie")
                else:
                    self.report.row(path, "no-data", "no-part-statement")
                continue
            if part.binding == "resolved":
                pick = lockfile.pick_key(self.lock, part.lockfile_key)
                if isinstance(pick, lockfile.Unlocked):
                    self.fail(path, "RHO6001", {
                        "key": part.lockfile_key,
                        "reason": UNLOCKED_REASONS[pick.reason]},
                        detail={"key": part.lockfile_key})
                    continue
            else:
                pick = picked.get(path)
                if pick is None:
                    self.analysis.found[path] = PartFacts(
                        "constraints", dict(part.constraints))
                    self.report.row(path, "no-data", "no-pick", detail={
                        "lockfile": lockfile.pick_instance(
                            self.lock, self.design, path).reason})
                    continue
            self.bind(path, instance, pick)

    def _names_abstract(self, pick) -> bool:
        """Whether an instance pick of this design names a component with
        `part abstract`; RHO6002 when it does not."""
        instance = self.model.instances.get(pick.instance)
        if instance is None:
            reason = "names no instance of the design"
        elif instance.kind != "component":
            reason = "names a module instance, which has no part"
        elif instance.part is None or instance.part.binding != "abstract":
            reason = "names a component with no `part abstract`"
        else:
            return True
        self.report.finding(
            "RHO6002", {"design": self.design, "instance": pick.instance,
                        "reason": reason},
            entity="/", primary=self.lock.span(pick.pointer + "/instance"))
        self.report.row("/", "fail", "pick-names-no-instance",
                        detail={"instance": pick.instance})
        return False

    def bind(self, path, instance, pick):
        verdict = self.records.verdict(pick)
        if verdict.code is not None:
            self.fail(path, verdict.code, verdict.params,
                      primary=self.lock.span(verdict.pointer),
                      fixits=verdict.fixits,
                      detail={"record": pick.record})
            return
        document = verdict.document
        echoes = _echoes(pick, document)
        if echoes:
            self.fail(path, "RHO6007", {
                "record": pick.record,
                "fields": [name for name, _pin, _rec in echoes],
                "pinned": [pinned for _n, pinned, _rec in echoes],
                "found": [str(found) for _n, _pin, found in echoes]},
                primary=self.lock.span(f"{pick.pointer}/{echoes[0][0]}"),
                detail={"record": pick.record})
            return
        binding = partdata.bind(document, instance.definition, [
            (port.name, port.role, port.pin_numbers)
            for port in instance.ports])
        conflicts = [p for p in binding.problems if p.check == "role-conflict"]
        if binding.problems and len(conflicts) == len(binding.problems):
            mapping = next(e for e in document["implements"]
                           if e["definition"] == instance.definition)["pins"]
            roles = {port.name: port.role for port in instance.ports}
            record_roles = {pin["name"]: pin["role"]
                            for pin in document["pins"]}
            ports = sorted(name for name in roles if name in mapping
                           and not partdata.compatible(
                               record_roles[mapping[name]], roles[name],
                               exact=instance.definition
                               in partdata.PART_SPECIFIC))
            self.fail(path, "RHO6009", {
                "part_id": pick.part_id, "definition": instance.definition,
                "ports": ports, "roles": [roles[name] for name in ports],
                "record_roles": [record_roles[mapping[name]]
                                 for name in ports]},
                detail={"record": pick.record})
            return
        if binding.problems:
            problems = [p.message for p in binding.problems]
            if document["schema_version"] == 0:
                # AMB-151 item 20: version 0 has no `implements`, so a
                # record of it loads, and never binds.
                problems.insert(0, "a version 0 record has no `implements` "
                                "map, so it never binds to a definition")
            self.fail(path, "RHO6008", {
                "part_id": pick.part_id, "definition": instance.definition,
                "problems": problems},
                detail={"record": pick.record})
            return
        part = instance.part
        if pick.key is None:
            current = lockfile.constraints_digest(part.constraints)
            if current != pick.constraints:
                span = self.lock.span(pick.pointer + "/constraints")
                self.fail(path, "RHO6011", {
                    "instance": path, "recorded": pick.constraints,
                    "current": current}, primary=span,
                    fixits=(FixIt("re-pin the pick to the constraints as "
                                  "they are now", "needs-review",
                                  (Edit(span, f'"{current}"'),)),),
                    detail={"record": pick.record})
                return
            unsatisfied, unverified, outside, ill_typed = _subset(
                part, binding, document)
            if unsatisfied:
                sites = [part.sites[name].span if name in part.sites
                         else instance.declaration
                         for name, _r, _f in unsatisfied]
                self.fail(path, "RHO6010", {
                    "part_id": pick.part_id,
                    "constraints": [name for name, _r, _f in unsatisfied],
                    "required": [required for _n, required, _f
                                 in unsatisfied],
                    "found": [found for _n, _r, found in unsatisfied]},
                    primary=sites[0],
                    secondary=tuple((span, f"`{name}` too") for span, (
                        name, _r, _f) in zip(sites[1:], unsatisfied[1:])),
                    detail={"constraints": [name for name, _r, _f
                                            in unsatisfied]})
                return
            for status, reason, names, actionable in (
                    ("undecided", "constraint-unverified", unverified, True),
                    ("not-run", "constraint-outside-subset", outside, True),
                    ("not-run", "constraint-ill-typed", ill_typed, False)):
                if names:
                    self.report.row(path, status, reason,
                                    actionable=actionable,
                                    detail={"constraints": names})
        if verdict.unchecked:
            self.report.row(path, "not-run", "record-check-unperformed",
                            detail={"record": pick.record,
                                    "checks": list(verdict.unchecked)})
        self.analysis.found[path] = PartFacts(
            "d3", dict(part.constraints), binding, pick.part_id,
            pick.revision, pick.record)
        self.report.row(path, "pass", "bound", detail={
            "part_id": pick.part_id, "record": pick.record,
            "revision": pick.revision,
            "pick": "keyed" if pick.key is not None else "instance"})


# A record that is no JSON, in words of the pass's own: the standard
# library's decoder words its errors differently from one Python to the
# next, and a diagnostic may not depend on the interpreter.
NOT_JSON = ("the record is not strict UTF-8 JSON: no key repeated in an "
            "object, no NaN or infinity, no lone surrogate escape, and no "
            f"nesting past {partdata.MAX_NESTING} levels")

# Why a `part "key"` has no pick, as RHO6001 says it.
UNLOCKED_REASONS = {
    "no-lockfile": "the compile root holds no rhoform.lock",
    "no-parts-section": "rhoform.lock has no parts section",
    "no-pick": "the parts section of rhoform.lock has no keyed pick of "
               "that key",
}


def run(model, analysis, report):
    """Pass 1: every component's part, against the lockfile's picks and
    the records they name (spec 05/09)."""
    _Pass(model, analysis, report, _context(model)).run()
