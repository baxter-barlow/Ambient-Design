"""T2 pin-role ERC and the L9b single-pin-net rule (L1b, AMB-52): pass 4.

Spec 05/04 is normative; this says how the code reads it.

THE TABLE. PAIR is KiCad's default pin-conflict matrix restricted to the
nine roles that connect (nc never does: RHO2024), as a total, symmetric
table over unordered role pairs: 45 cells, each ok, warning or error.
"Lattice" in T2 means this table plus an order-independent fold over a
net's pins (`fold`): the baseline is no join-semilattice -- two open
collectors are fine where two outputs are not -- so no order is derived
from it and none is imposed on it.

WHAT IS COUNTED. A net's members split three ways (rhoform.check.model):
component pins, which are physical; module ports below the root, which
join nets across the hierarchy and are never counted; and the root's own
ports, which are external terminals -- something outside reaches the net
through them. The electrical rules (the table, undriven inputs, missing
pulls, isolated inputs, shorted parts, decoupling) count FITTED pins
only: a DNP instance adds no driver, pull or capacitor (spec 05 section
1), and a net whose verdict would change were its DNP parts fitted gets
a `depends-on-dnp` row in the report. The connectivity rules (unconnected
pins, single-pin nets, nets with no pins) count every pin: a DNP part's
pads are still on the board. Ground typing is the ground pass's
(`analysis.ground`): a ground-typed net carries an implicit reference, so
several supply returns may share it and an input on it is driven.

ONE FINDING PER DEFINITION. Params spell nets and pins as the module
whose body declares them writes them, never by instance path, so the
copies one module instantiated twice makes of a defect agree on code,
params and spans, and the reporter makes them one finding (spec 05
section 1), keeping an entity only when the copies are one net.

Power-input sourcing (KiCad's power-pin-not-driven) is not here: whether
a supply reaches a power_in pin through a fuse, a ferrite or a jumper is
a domain question, and T5 (the domains pass) owns it.
"""

from collections import Counter
from dataclasses import dataclass
import re

from ..codeset.erc import CODES
from ..diagnostics import Edit, FixIt, span_from_bytes
from ..elaborate import SINGLE_PIN_HARDWARE
from .model import PinRole

NAME = "erc"
OWNER = "erc"
IMPLEMENTED = True

VERDICTS = ("ok", "warning", "error")

# The roles a pin may connect with, in PinRole order.
CONNECTABLE = tuple(role for role in PinRole if role != "nc")

# KiCad's ERR and WAR cells among them (open_drain and open_collector are
# both its open collector); every other cell is ok.
_ERRORS = (
    ("output", "output"),
    ("output", "power_out"),
    ("output", "open_drain"),
    ("output", "open_collector"),
    ("power_out", "power_out"),
    ("power_out", "open_drain"),
    ("power_out", "open_collector"),
    ("power_out", "tri_state"),
)
_WARNINGS = (
    ("output", "tri_state"),
    ("bidirectional", "power_out"),
    ("tri_state", "power_in"),
    ("tri_state", "open_drain"),
    ("tri_state", "open_collector"),
)
PAIR = {frozenset((a, b)): "ok"
        for index, a in enumerate(CONNECTABLE) for b in CONNECTABLE[index:]}
PAIR.update({frozenset(cell): "error" for cell in _ERRORS})
PAIR.update({frozenset(cell): "warning" for cell in _WARNINGS})

# A ground-typed net is the reference: several supply returns share it, so
# these error cells are ok there, and each pin also meets the reference
# itself -- a push-pull or tri-state output shorts against it, a
# bidirectional pin tied to it is KiCad's bidirectional-with-a-rail.
GROUND_OK = frozenset(frozenset(cell) for cell in (
    ("power_out", "power_out"),
    ("power_out", "open_drain"),
    ("power_out", "open_collector"),
))
REFERENCE = {
    "power_in": "ok",
    "power_out": "ok",
    "passive": "ok",
    "bidirectional": "warning",
    "open_drain": "ok",
    "open_collector": "ok",
    "tri_state": "error",
    "input": "ok",
    "output": "error",
}

# What can bring a net to a level an input reads: passive counts, since a
# resistor or a capacitor sets a node (a divider, an RC); single-pin
# hardware does not, though it is a passive pin. What can pull an open
# drain up is narrower: a two-terminal part whose other pin is on a
# ground-typed net (a pull-down, a delay or filter capacitor, a clamp)
# holds the line low and never lifts it.
DRIVING = frozenset({"output", "power_out", "bidirectional", "tri_state",
                     "passive"})
PULL_LOW = frozenset({"open_drain", "open_collector"})
FLOATING_WHEN_ISOLATED = ("input", "power_in")

CAPACITOR = "rhoform.lib.passive.Capacitor"
DNP_REASON = "depends-on-dnp"
NO_GROUND_REASON = "no-ground-typed-net"


def pair_matrix() -> tuple:
    """The table as spec 05/04 restates it: a row per role, a column per
    role, both in CONNECTABLE order."""
    return tuple((a,) + tuple(PAIR[frozenset((a, b))] for b in CONNECTABLE)
                 for a in CONNECTABLE)


def reference_rows() -> tuple:
    """(role, its verdict against a ground-typed net's reference)."""
    return tuple((role, REFERENCE[role]) for role in CONNECTABLE)


def code_rows() -> tuple:
    """(code, slug, severity) of every code this pass reports."""
    return tuple((entry.code, entry.slug, entry.severity) for entry in CODES)


def fold(roles, ground: bool = False) -> dict:
    """{"error": roles, "warning": roles}: the roles of a net's pins that
    take part in a cell of that verdict. A pair is two distinct pins, so
    a role meets itself only when two pins hold it. Order-independent:
    only how many pins hold each role counts."""
    counts = Counter(roles)
    present = [role for role in CONNECTABLE if counts[role]]
    found = {"error": set(), "warning": set()}
    for index, a in enumerate(present):
        for b in present[index:]:
            if a == b and counts[a] < 2:
                continue
            cell = frozenset((a, b))
            verdict = "ok" if ground and cell in GROUND_OK else PAIR[cell]
            if verdict != "ok":
                found[verdict].update(cell)
        if ground and REFERENCE[a] != "ok":
            found[REFERENCE[a]].add(a)
    return found


@dataclass(frozen=True)
class NetView:
    """One net as ERC counts it, for T5 and T10 too. Members are
    rhoform.check.model.Member, in IR order."""

    name: str
    physical: tuple  # every component pin
    fitted: tuple  # the physical pins whose instance is not DNP
    hierarchical: tuple  # module ports below the root: never counted
    root_ports: tuple  # the root's ports: external terminals
    ground: bool
    isolated: bool

    def counts(self) -> dict:
        """{role: how many fitted pins hold it}."""
        return dict(Counter(member.role for member in self.fitted))


@dataclass(frozen=True)
class ErcAnalysis:
    views: dict  # net name -> NetView, in IR order


def run(model, analysis, report):
    """Pass 4: every rule over every net and every component."""
    views = {}
    for name in model.nets:
        hierarchical = model.hierarchical_members[name]
        physical = model.physical_members[name]
        views[name] = NetView(
            name, physical,
            tuple(m for m in physical if not model.instances[m.path].dnp),
            tuple(m for m in hierarchical if m.path != "/"),
            tuple(m for m in hierarchical if m.path == "/"),
            analysis.ground.is_ground(name), name in model.isolated)
    analysis.erc = ErcAnalysis(views)
    _Rules(model, analysis.ground, views, report).run()


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] or "/"


def _within(path: str, scope: str) -> bool:
    return scope == "/" or path == scope or path.startswith(scope + "/")


def _is_capacitor(instance) -> bool:
    """A two-terminal component that is the library's capacitor or states
    a capacitance, as a parameter or a part constraint."""
    if len(instance.ports) != 2:
        return False
    part = instance.part
    return (instance.definition == CAPACITOR
            or "capacitance" in instance.parameters
            or (part is not None and "capacitance" in part.constraints))


class _Rules:
    def __init__(self, model, ground, views, report):
        self.model = model
        self.ground = ground
        self.views = views
        self.report = report
        self.files = {source.path: source.data
                      for source in model.design.files}
        # The module instances below the root, by the trace a net declared
        # in their body extends: how a net finds the body declaring it.
        self.bodies = {}
        for path, instance in model.instances.items():
            if instance.kind == "module" and path != "/":
                self.bodies.setdefault(tuple(instance.trace), []).append(path)
        # net -> (capacitor, the net its other pin is on), for decoupling.
        self.capacitors = {}
        for path in model.components:
            instance = model.instances[path]
            if not _is_capacitor(instance):
                continue
            nets = [model.net_of.get((path, port.name))
                    for port in instance.ports]
            if None in nets:
                continue
            for here, there in (nets, nets[::-1]):
                self.capacitors.setdefault(here, []).append((path, there))
        self.grounded = any(view.ground for view in views.values())

    # -- spelling: names as the declaring module writes them

    def scope(self, net) -> str:
        """The module instance whose body holds the net's declaration: the
        one whose trace the net's extends -- of the members of a module
        array, which share one, the least the declaration's own statement
        can name, as the elaborator picks a net's site."""
        trace = tuple(net.trace[1:])
        if not trace:
            return "/"
        for path in sorted(self.bodies.get(trace, ())):
            if any(member == path or _parent(member) == path
                   for member, _port in net.members):
                return path
        return "/"  # pragma: no cover - every net is declared somewhere

    @staticmethod
    def spelled(scope: str, path: str, port: str) -> str:
        """`port`, `child.port` or `a/b.port` inside the scope; outside it
        (a net declared in a module that its parent extends), the path."""
        if path == scope:
            return port
        if scope == "/":
            return f"{path[1:]}.{port}"
        if path.startswith(scope + "/"):
            return f"{path[len(scope) + 1:]}.{port}"
        return f"{path}.{port}"

    def net_name(self, scope: str, net) -> str:
        """The net's name without the scope's qualification: its label as
        the module declares it, or `N_` and its least member there."""
        if scope == "/":
            return net.name
        for path, port in net.members:
            if net.name == f"N_{path[1:]}.{port}":
                return "N_" + self.spelled(scope, path, port)
        if net.name.startswith(scope[1:] + "/"):
            return net.name[len(scope):]
        return net.name

    def pins(self, scope, members) -> list:
        return [self.spelled(scope, m.path, m.port) for m in members]

    def at(self, scope, members) -> tuple:
        """Secondary spans: where each pin joins the net, labelled."""
        spans, seen = [], set()
        for member in members:
            sites = self.model.endpoint_spans.get((member.path, member.port))
            if sites and sites[0] not in seen:
                seen.add(sites[0])
                pin = self.spelled(scope, member.path, member.port)
                spans.append((sites[0], f"`{pin}`, {member.role}"))
        return tuple(spans)

    # -- the rules

    def run(self):
        for name, view in self.views.items():
            net = self.model.nets[name]
            scope = self.scope(net)
            found = self.electrical(view, scope, view.fitted)
            if len(view.fitted) != len(view.physical):
                fitted = self.electrical(view, scope, view.physical)
                codes = sorted(code for code, _p, _s in found)
                if codes != sorted(code for code, _p, _s in fitted):
                    self.report.row(
                        name, "fail" if found else "pass", DNP_REASON,
                        detail={
                            "dnp": sorted({m.path for m in view.physical
                                           if m not in view.fitted}),
                            "codes": codes,
                            "codes_if_fitted": sorted(
                                code for code, _p, _s in fitted)})
            for code, params, secondary in found + self.connectivity(
                    view, net, scope):
                self.report.finding(code, params, entity=name,
                                    secondary=secondary)
        self.unconnected()
        self.shorted()
        if not self.grounded:
            supplied = [name for name, view in self.views.items()
                        if not view.isolated
                        and any(m.role == "power_in" for m in view.fitted)]
            if supplied:
                # The decoupling rule needs a ground to decouple to: with
                # none typed it cannot decide, and says so (L2c's typing,
                # or a label, closes it).
                self.report.row("/", "no-data", NO_GROUND_REASON,
                                actionable=True, detail={"nets": supplied})

    def electrical(self, view, scope, members) -> list:
        """(code, params, secondary) of the rules that read what drives a
        net, over `members` (its fitted pins, or all of them)."""
        found = []
        net = self.net_name(scope, self.model.nets[view.name])
        if view.isolated:
            for member in members:
                if member.role in FLOATING_WHEN_ISOLATED:
                    found.append((
                        "RHO3107",
                        {"member": self.spelled(scope, member.path,
                                                member.port),
                         "role": member.role}, ()))
            return found
        verdicts = fold([m.role for m in members], view.ground)
        for code, verdict in (("RHO3101", "error"), ("RHO3102", "warning")):
            pins = [m for m in members if m.role in verdicts[verdict]]
            if pins:
                found.append((code, {"net": net,
                                     "members": self.pins(scope, pins),
                                     "roles": [m.role for m in pins]},
                              self.at(scope, pins)))
        if view.ground:
            return found
        drivers = [m for m in members if m.role in DRIVING
                   and self.model.instances[m.path].hardware_kind
                   not in SINGLE_PIN_HARDWARE]
        pulls = [m for m in members if m.role in PULL_LOW]
        inputs = [m for m in members if m.role == "input"]
        if inputs and not drivers and not pulls and not view.root_ports:
            found.append(("RHO3103", {"net": net,
                                      "inputs": self.pins(scope, inputs)},
                          self.at(scope, inputs)))
        lifts = [m for m in drivers if not self.to_ground(m)]
        if pulls and not lifts and not view.root_ports:
            found.append(("RHO3104", {"net": net,
                                      "pins": self.pins(scope, pulls)},
                          self.at(scope, pulls)))
        supplies = [m for m in members if m.role == "power_in"]
        if supplies and self.grounded and not self.decoupled(
                view.name, {m.path for m in members}):
            found.append(("RHO3110", {"net": net,
                                      "pins": self.pins(scope, supplies)},
                          self.at(scope, supplies)))
        return found

    def to_ground(self, member) -> bool:
        """Whether a passive pin's part has two pins and the other one is
        on a ground-typed net, so it can hold a line low but not lift it."""
        instance = self.model.instances[member.path]
        if member.role != "passive" or len(instance.ports) != 2:
            return False
        (other,) = (self.model.net_of.get((member.path, port.name))
                    for port in instance.ports if port.name != member.port)
        return other is not None and self.ground.is_ground(other)

    def decoupled(self, name, present) -> bool:
        """Whether a present capacitor joins the net to a ground-typed
        net."""
        return any(path in present and there != name
                   and self.ground.is_ground(there)
                   for path, there in self.capacitors.get(name, ()))

    def connectivity(self, view, net, scope) -> list:
        """RHO3106 and RHO3108, over every pin, DNP or not. A root port is
        a terminal, and an isolated net is declared."""
        if view.isolated or view.root_ports:
            return []
        name = self.net_name(scope, net)
        if len(view.physical) == 1:
            (pin,) = view.physical
            # A module port its parent connects to nothing: the parent is
            # where the connection is missing.
            open_ports = tuple(
                (self.model.declaration(port.path),
                 f"`{port.port}` is connected to nothing outside it here")
                for port in view.hierarchical
                if all(_within(path, port.path) for path, _ in net.members))
            return [("RHO3106",
                     {"net": name,
                      "member": self.spelled(scope, pin.path, pin.port)},
                     open_ports)]
        if not view.physical:
            return [("RHO3108",
                     {"net": name, "ports": self.pins(scope,
                                                      view.hierarchical)},
                     ())]
        return []

    def unconnected(self):
        """RHO3105: one finding per instance, every pin no net holds."""
        by_instance = {}
        for member in self.model.unconnected:
            by_instance.setdefault(member.path, []).append(member)
        for path, members in by_instance.items():
            segment = path.rsplit("/", 1)[1]
            self.report.finding(
                "RHO3105",
                {"instance": segment,
                 "ports": [m.port for m in members],
                 "roles": [m.role for m in members]},
                entity=path, fixits=self.isolate(path, segment, members))

    def isolate(self, path, segment, members) -> tuple:
        """The needs-review fix-it: an `isolated` line per pin after the
        instance's declaration, when that is a `name = new` statement
        (a table row has no line of its own to follow)."""
        declaration = self.model.instances[path].declaration
        data = self.files.get(declaration.file)
        base = re.escape(segment.split("[", 1)[0])
        if data is None or not re.match(
                rf"{base}\s*=\s*new\b".encode(),
                data[declaration.byte_start:declaration.byte_end]):
            return ()
        indent = " " * (declaration.col_start - 1)
        text = "".join(f"\n{indent}isolated {segment}.{m.port}"
                       for m in members)
        where = span_from_bytes(declaration.file, data, declaration.byte_end,
                                declaration.byte_end)
        return (FixIt(
            "declare each pin isolated, if it is meant to stay unconnected",
            "needs-review", (Edit(where, text),)),)

    def shorted(self):
        """RHO3109: a two-terminal component whose pins are one net."""
        for path in self.model.components:
            instance = self.model.instances[path]
            if len(instance.ports) != 2:
                continue
            nets = {self.model.net_of.get((path, port.name))
                    for port in instance.ports}
            if len(nets) != 1 or None in nets:
                continue
            net = self.model.nets[nets.pop()]
            if instance.dnp:
                self.report.row(path, "pass", DNP_REASON,
                                detail={"dnp": [path], "codes": [],
                                        "codes_if_fitted": ["RHO3109"]})
                continue
            pins = [m for m in self.model.physical_members[net.name]
                    if m.path == path]
            self.report.finding(
                "RHO3109",
                {"instance": path.rsplit("/", 1)[1],
                 "net": self.net_name(self.scope(net), net)},
                entity=path, secondary=self.at(_parent(path), pins))
