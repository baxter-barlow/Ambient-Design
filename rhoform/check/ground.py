"""Ground architecture, GA passes 1-4 (L2c, AMB-54): pass 3.

GA-1..GA-17 are normative by reference and spec 05/05 is normative on how
they are read here; this says how the code reads it. Ground analysis is
the prerequisite for the rest of T5 (GA Checker Notes section 1), so it
runs before ERC, whose ground exemptions read `is_ground`.

CONDUCTION GROUPS come from each component's rules (Instance.rules, its
definition's or a `rule` statement's): a component with no rule that
splits it is one group, the GA default. `open` and `bridge` pins are each
a group of their own, and so are a `connector`'s contacts; the coupling
words (`conduct`, `pass`, `diode`, `switch`, `tie`, `source`, `regulate`,
`feedback`) join the pins they name. A component that declares a `side`
is an isolation BARRIER: one group per side, conducting within the side
and never across it.

PASS 1, the isolation partition, is declared, not observed: a union-find
over nets, taking every fitted barrier's sides and then every other
fitted component's groups, in IR order, where each side seeds its nets
with itself. A union that would join two classes some barrier keeps
apart is refused, so a bridge across a barrier cannot launder itself
into a merge; the component whose group it was spans the barrier
(RHO4005, RHO4008 for a net-tie). PASS 2 types grounds: a net is
ground-typed when it carries a `ground_domain` label or a `ground_kind`
attribute (GA-1 definition a), or holds a fitted pin a `ground` rule
names, the default ground a design gets from its parts with no
annotation at all (definition c). The GA-2 kind meet runs here over
Net.attribute_sites, so RHO4001 carries both spans. PASS 3 keeps two
union-finds over ground nets and never conflates them: ground domains
(net-ties and galvanic passives unify) and the tie graph (net-ties
alone), which must be a forest (RHO4002). PASS 4 scans for the rest of
the catalog but RHO4006, which needs interfaces (L3).

A DNP instance is absent (spec 05 section 1): it adds no union, types no
net and is scanned for nothing; a DNP part that would relate or straddle
domains were it fitted gets a `depends-on-dnp` row.

Domain ids are the least member net's name (GA notes section 1), and the
computed ids go to the check report, never to the IR: Net.ground_domain
keeps its authored meaning (D18). Params name nets and instances as the
IR does, the ids among them.
"""

from dataclasses import dataclass
import re

from ..codeset.ground import CODES

NAME = "ground"
OWNER = "ground"
IMPLEMENTED = True

# The GA-2 kinds, in the order lang/grammar/rhoform_syntax.py's
# CLOSED_VOCABULARIES["ground_kind"] lists them: transcribed, not imported
# (rhoform never imports lang.grammar at import time); test_ground.py
# holds the two together. `unspecified` is the lattice's top.
KINDS = ("unspecified", "signal", "power", "chassis", "earth")
UNSPECIFIED = "unspecified"
# The kinds a bond to which is safety-relevant (GA-11).
SAFETY_KINDS = ("chassis", "earth")
EARTH = "earth"

SIDE = "side"
TIE = "tie"
BRIDGE = "bridge"
OPEN = "open"
CONNECTOR = "connector"
GROUND = "ground"
# Rule words that join the pins they name into one conduction group.
COUPLING = frozenset({"conduct", "diode", "feedback", "pass", "regulate",
                      "source", "switch", TIE})
# The declared galvanic passives (GA section 1.4): these unify the ground
# domains of the ground nets they join.
GALVANIC = frozenset({"conduct", "pass", "switch"})
PASSIVE = "passive"

DNP_REASON = "depends-on-dnp"
NO_GROUND_REASON = "no-ground-domain"


def word_rows() -> tuple:
    """(rule word, what it does to its component here), for every word
    this pass reads, as spec 05/05 restates them."""
    effects = {word: "joins its pins" for word in COUPLING}
    effects.update({word: "joins its pins; a galvanic passive"
                    for word in GALVANIC})
    effects.update({
        BRIDGE: "a group per pin; a safety capacitor",
        CONNECTOR: "a group per contact",
        GROUND: "types its pins' nets ground",
        OPEN: "a group per pin",
        SIDE: "a group per side; a barrier",
        TIE: "joins its two pins; a net-tie",
    })
    return tuple(sorted(effects.items()))


def code_rows() -> tuple:
    """(code, slug, severity) of every code this pass reports."""
    return tuple((entry.code, entry.slug, entry.severity)
                 for entry in CODES if not entry.reserved)


@dataclass(frozen=True)
class Conduction:
    """One component's conduction model, from its rules. Pins are port
    names; every tuple is sorted."""

    groups: tuple  # tuple of pin tuples, galvanic connectivity within each
    sides: tuple = ()  # (side name, pins) of a barrier, by name
    tie: tuple | None = None  # the two pins of a well-formed net-tie
    bridges: tuple = ()  # pin pairs of `bridge` rules (GA-12)
    opens: tuple = ()  # pin tuples of `open` rules
    contacts: tuple = ()  # pins a `connector` rule makes external contacts
    grounds: tuple = ()  # pins `ground` rules name
    galvanic: tuple = ()  # pin tuples that unify ground domains
    malformed: tuple = ()  # (reason, detail) of GA rules not read

    @property
    def barrier(self) -> bool:
        return bool(self.sides)


def conduction(instance) -> Conduction:
    """The conduction model of one component instance."""
    pins = sorted(port.name for port in instance.ports)
    rules = instance.rules
    grounds = tuple(sorted({pin for rule in rules if rule.word == GROUND
                            for pin in rule.pins}))
    sides = {}
    for rule in rules:
        if rule.word == SIDE:
            sides.setdefault(rule.side, set()).update(rule.pins)
    if sides:
        named = {pin for members in sides.values() for pin in members}
        groups = [tuple(sorted(members)) for _name, members
                  in sorted(sides.items())]
        groups += [(pin,) for pin in pins if pin not in named]
        return Conduction(
            tuple(sorted(groups)),
            sides=tuple((name, tuple(sorted(members)))
                        for name, members in sorted(sides.items())),
            grounds=grounds)
    malformed = []
    tie = None
    ties = [rule for rule in rules if rule.word == TIE]
    if ties:
        named = set(ties[0].pins)
        if len(ties) == 1 and len(named) == 2 and named == set(pins):
            tie = tuple(sorted(named))
        else:
            malformed.append(("malformed-tie", {
                "ties": len(ties), "pins": pins,
                "tie_pins": sorted({p for r in ties for p in r.pins})}))
    split, bridges, opens = set(), [], []
    for rule in rules:
        if rule.word not in (OPEN, BRIDGE):
            continue
        split.update(rule.pins)
        if rule.word == OPEN:
            opens.append(tuple(sorted(set(rule.pins))))
        elif len(set(rule.pins)) == 2:
            bridges.append(tuple(sorted(set(rule.pins))))
        else:
            malformed.append(("malformed-bridge",
                              {"bridge_pins": sorted(set(rule.pins))}))
    connectors = [rule for rule in rules if rule.word == CONNECTOR]
    contacts = {pin for rule in connectors for pin in rule.pins}
    if any(not rule.pins for rule in connectors):
        covered = {pin for rule in rules if rule.word != CONNECTOR
                   for pin in rule.pins + ((rule.other,)
                                           if rule.other else ())}
        contacts.update(pin for pin in pins if pin not in covered)
    split.update(contacts)
    groups = _Classes(pins)
    body = [pin for pin in pins if pin not in split]
    for pin in body[1:]:
        groups.union(body[0], pin)
    galvanic = []
    for rule in rules:
        joined = sorted(set(rule.pins + ((rule.other,) if rule.other
                                         else ())))
        if rule.word in COUPLING:
            for pin in joined[1:]:
                groups.union(joined[0], pin)
        if rule.word in GALVANIC and len(joined) > 1:
            galvanic.append(tuple(joined))
    if not rules and len(pins) == 2 and all(
            port.role == PASSIVE for port in instance.ports):
        # The GA default for a two-terminal passive with no rules yet: a
        # galvanic passive (R, L, ferrite, fuse).
        galvanic.append(tuple(pins))
    return Conduction(
        tuple(sorted(tuple(members) for members in groups.classes())),
        tie=tie, bridges=tuple(sorted(set(bridges))),
        opens=tuple(sorted(set(opens))), contacts=tuple(sorted(contacts)),
        grounds=grounds,
        galvanic=tuple(sorted(set(galvanic))), malformed=tuple(malformed))


class _Classes:
    """A union-find over names whose root is always its class's least
    member, so a class's id is `find` of any member, whatever the order
    of unions."""

    def __init__(self, items=()):
        self.parent = {item: item for item in items}

    def find(self, item):
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a, b):
        """Join the classes of a and b; the surviving root."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        if rb < ra:
            ra, rb = rb, ra
        self.parent[rb] = ra
        return ra

    def classes(self) -> list:
        """Every class as a sorted list, the classes in id order."""
        out = {}
        for item in sorted(self.parent):
            out.setdefault(self.find(item), []).append(item)
        return [out[root] for root in sorted(out)]


class GroundAnalysis:
    """What the ground pass concluded, for the passes after it. Nets are
    IR net names, components instance paths; every collection is in
    canonical order."""

    def __init__(self, models, ground_nets, kinds, ground, isolation,
                 edges):
        self._models = models
        self.ground_nets = tuple(sorted(ground_nets))
        self._ground = frozenset(ground_nets)
        self._kinds = kinds
        self._ground_of = {net: ground.find(net) for net in ground_nets}
        self._isolation_of = {net: isolation.find(net)
                              for net in isolation.parent}
        self.ground_domains = {members[0]: tuple(members)
                               for members in ground.classes()}
        self.isolation_domains = {members[0]: tuple(members)
                                  for members in isolation.classes()}
        # (tie instance path, net, net): the GA-6 tie graph's edges.
        self.tie_graph = tuple(edges)
        # Every component a well-formed `tie` makes a net-tie (GA-4).
        self.net_ties = tuple(path for path, model in models.items()
                              if model.tie is not None)

    def is_ground(self, net: str) -> bool:
        return net in self._ground

    def ground_kind(self, net: str) -> str | None:
        """A ground-typed net's GA-2 kind; None for a net that is not
        ground-typed, or whose kinds have no meet (RHO4001)."""
        return self._kinds.get(net)

    def ground_domain(self, net: str) -> str | None:
        """The id of a ground-typed net's ground domain. A net that is not
        ground-typed has no ground domain of its own here: what it is
        referenced to is T5's question (L3)."""
        return self._ground_of.get(net)

    def isolation_domain(self, net: str) -> str:
        return self._isolation_of[net]

    def conduction_groups(self, path: str) -> tuple:
        """A component's conduction groups: tuples of its port names."""
        return self._models[path].groups

    def barriers(self) -> dict:
        """{barrier instance path: ((side, pins), ...)}."""
        return {path: model.sides for path, model in self._models.items()
                if model.barrier}


def run(model, analysis, report):
    analysis.ground = _Pass(model, report).run()


class _Pass:
    def __init__(self, model, report):
        self.model = model
        self.report = report
        self.instances = model.instances
        self.models = {path: conduction(self.instances[path])
                       for path in model.components}
        self.fitted = tuple(path for path in model.components
                            if not self.instances[path].dnp)
        self.files = {source.path: source.data
                      for source in model.design.files}
        # Nets holding a fitted component pin: what the board has.
        self.live = frozenset(
            name for name in model.nets
            if any(not self.instances[m.path].dnp
                   for m in model.physical_members[name]))

    def nets(self, path, pins) -> list:
        """The nets `pins` of `path` are on, each once, in pin order."""
        out = []
        for pin in pins:
            net = self.model.net_of.get((path, pin))
            if net is not None and net not in out:
                out.append(net)
        return out

    def run(self) -> GroundAnalysis:
        for path in self.model.components:
            for reason, detail in self.models[path].malformed:
                self.report.row(path, "no-data", reason, actionable=True,
                                detail=detail)
        self.partition()
        self.typing()
        self.domains()
        self.scan()
        result = GroundAnalysis(self.models, self.ground_nets, self.kinds,
                                self.ground, self.isolation, self.edges)
        self.rows(result)
        return result

    # -- pass 1: the isolation partition

    def partition(self):
        self.isolation = _Classes(self.model.nets)
        # class root -> {barrier: sides of it seeded in the class}
        self.seeds = {}
        self.wires = {}  # net -> the least barrier two sides of which it holds
        for path in self.fitted:
            for side, pins in self.models[path].sides:
                for net in self.nets(path, pins):
                    self.seeds.setdefault(net, {}).setdefault(
                        path, set()).add(side)
        for net, barriers in sorted(self.seeds.items()):
            for barrier, sides in sorted(barriers.items()):
                if len(sides) > 1:
                    self.wires.setdefault(net, barrier)
        # A barrier conducts within each side (GA section 1.1), and its
        # sides go first: they are declarations, so a part bridging them
        # is what a refused union reports, never the side itself.
        joining = [(path, pins) for path in self.fitted
                   for _side, pins in self.models[path].sides]
        joining += [(path, group) for path in self.fitted
                    if not self.models[path].barrier
                    for group in self.models[path].groups]
        for path, group in joining:
            nets = self.nets(path, group)
            for net in nets[1:]:
                a, b = (self.isolation.find(nets[0]),
                        self.isolation.find(net))
                if a == b or self.separating(a, b):
                    continue
                seeds = {}
                for root in (a, b):
                    for barrier, sides in self.seeds.pop(root, {}).items():
                        seeds.setdefault(barrier, set()).update(sides)
                root = self.isolation.union(a, b)
                if seeds:
                    self.seeds[root] = seeds

    def separating(self, a, b) -> str | None:
        """The least barrier that keeps classes a and b apart: one with
        sides seeded in both and no side in both."""
        here, there = self.seeds.get(a, {}), self.seeds.get(b, {})
        for barrier in sorted(set(here) & set(there)):
            if not here[barrier] & there[barrier]:
                return barrier
        return None

    def spanned(self, path, group):
        """(domain, domain, barrier) when a component's group lands in two
        classes a barrier keeps apart: the least such pair."""
        roots = sorted({self.isolation.find(net)
                        for net in self.nets(path, group)})
        for i, a in enumerate(roots):
            for b in roots[i + 1:]:
                barrier = self.separating(a, b)
                if barrier is not None:
                    return a, b, barrier
        return None

    # -- pass 2: ground typing and the GA-2 meet

    def typing(self):
        sites = self.model.attribute_sites
        ground = set()
        for name, net in self.model.nets.items():
            if net.ground_domain is not None or "ground_domain" in sites[
                    name] or "ground_kind" in sites[name]:
                ground.add(name)
        for path in self.fitted:
            ground.update(self.nets(path, self.models[path].grounds))
        self.ground_nets = ground
        self.kinds = {}
        for name in sorted(ground):
            written = sites[name].get("ground_kind", ())
            specific = [kind for kind in KINDS[1:]
                        if any(value == kind for value, _span in written)]
            if len(specific) <= 1:
                self.kinds[name] = specific[0] if specific else UNSPECIFIED
                continue
            first, second = specific[0], specific[1]
            span_a = next(span for value, span in written if value == first)
            span_b = next(span for value, span in written
                          if value == second)
            net_a = self.label_at(span_a) or name
            net_b = self.label_at(span_b) or name
            self.report.finding(
                "RHO4001",
                {"net_a": net_a, "kind_a": first, "net_b": net_b,
                 "kind_b": second},
                entity=name, primary=span_b,
                secondary=((span_a, f"`{net_a}` is {first} here"),))

    def label_at(self, span) -> str | None:
        """The label of the net block whose attribute list holds `span`,
        as its module writes it."""
        data = self.files.get(span.file)
        if data is None:
            return None
        for match in _NET_HEAD.finditer(data):
            close = _closing(data, match.end())
            if match.end() <= span.byte_start and span.byte_end <= close:
                return match.group(1).decode()
        return None

    # -- pass 3: ground domains and the tie graph

    def domains(self):
        self.ground = _Classes(self.ground_nets)
        self.ties = _Classes(self.ground_nets)
        self.edges = []
        self.bonds = []  # (component, nets, how)
        for path in self.fitted:
            model = self.models[path]
            if model.tie is not None:
                self.tie(path, model)
            elif not model.barrier:
                for pins in model.galvanic:
                    nets = [net for net in self.nets(path, pins)
                            if net in self.ground_nets]
                    if len(nets) > 1:
                        self.bonds.append((path, tuple(nets), "galvanic"))
                        self.unify(nets)
            for pins in model.bridges:
                nets = [net for net in self.nets(path, pins)
                        if net in self.ground_nets]
                if len(nets) > 1:
                    self.bonds.append((path, tuple(nets), "bridge"))

    def unify(self, nets):
        """One ground domain for `nets`; an earth-kind net stays its own
        (GA-10: earth is no reference, and joins no domain)."""
        nets = [net for net in nets if self.kinds.get(net) != EARTH]
        for net in nets[1:]:
            self.ground.union(nets[0], net)

    def tie(self, path, model):
        nets = self.nets(path, model.tie)
        if len(nets) == 1 and all(self.model.net_of.get((path, pin))
                                  for pin in model.tie):
            self.report.finding("RHO4009", {"tie": path, "net": nets[0]},
                                entity=path)
            return
        if len(nets) != 2:
            return  # a pin left open is ERC's (RHO3105)
        if self.spanned(path, model.tie) is not None:
            return  # reported by the scan; no union, no edge
        a, b = nets
        if a not in self.ground_nets or b not in self.ground_nets:
            return  # GA-9: domain-transparent, like a direct connection
        self.bonds.append((path, (a, b), "tie"))
        self.unify([a, b])
        if self.ties.find(a) == self.ties.find(b):
            self.loop(path, a, b)
            return
        self.ties.union(a, b)
        self.edges.append((path, a, b))

    def loop(self, path, a, b):
        """RHO4002: the cycle the tie `path` closes, net and tie by turn,
        from `a` through the forest to `b` and back over `path`."""
        adjacent = {}
        for tie, x, y in self.edges:
            adjacent.setdefault(x, []).append((y, tie))
            adjacent.setdefault(y, []).append((x, tie))
        trail = {a: None}
        queue = [a]
        while queue:
            here = queue.pop(0)
            for there, tie in sorted(adjacent.get(here, ())):
                if there not in trail:
                    trail[there] = (here, tie)
                    queue.append(there)
        cycle = [b]
        while trail[cycle[-1]] is not None:
            here, tie = trail[cycle[-1]]
            cycle += [tie, here]
        cycle.reverse()
        cycle += [path, a]
        self.report.finding(
            "RHO4002", {"cycle": cycle}, entity=path,
            secondary=tuple((self.model.declaration(tie), "in the cycle")
                            for tie in cycle[1::2] if tie != path))

    # -- pass 4: the scans

    def scan(self):
        for net, barrier in sorted(self.wires.items()):
            domain = self.isolation.find(net)
            self.report.finding(
                "RHO4005",
                {"component": net, "domain_a": domain, "domain_b": domain,
                 "barrier_component": barrier},
                entity=net,
                secondary=((self.model.declaration(barrier), "the barrier"),))
        spanning = set()
        for path in self.fitted:
            model = self.models[path]
            groups = (tuple(pins for _side, pins in model.sides)
                      if model.barrier else model.groups)
            for group in groups:
                found = self.spanned(path, group)
                if found is None:
                    continue
                spanning.add(path)
                a, b, barrier = found
                secondary = ((self.model.declaration(barrier),
                              "the barrier"),)
                if model.tie is not None:
                    self.report.finding(
                        "RHO4008", {"tie": path,
                                    "barrier_component": barrier},
                        entity=path, secondary=secondary)
                else:
                    self.report.finding(
                        "RHO4005",
                        {"component": path, "domain_a": a, "domain_b": b,
                         "barrier_component": barrier},
                        entity=path, secondary=secondary)
                break
            if model.barrier:
                continue
            if path not in spanning and self.bridged(path, model):
                spanning.add(path)
            if path in spanning or model.tie is not None:
                continue
            self.straddles(path, model)
        for path in self.fitted:
            model = self.models[path]
            for pin in model.grounds:
                net = self.model.net_of.get((path, pin))
                if net is not None and self.kinds.get(net) == EARTH:
                    self.report.finding(
                        "RHO4003", {"net": net, "referencing_entity": path},
                        entity=path)
                    break
        noted = set()
        for path, nets, _how in self.bonds:
            kinds = [self.kinds.get(net) for net in nets]
            if path in noted or not any(k in SAFETY_KINDS for k in kinds):
                continue
            noted.add(path)
            self.report.finding(
                "RHO4011", {"bond": path,
                            "boundary": EARTH if EARTH in kinds
                            else "chassis"},
                entity=path)
        self.disjoint()

    def bridged(self, path, model) -> bool:
        """RHO4004: an `open` pair, which no `bridge` declares, across a
        barrier or between a chassis or earth ground and another ground
        of a different kind (GA-12, checked by position)."""
        for pins in model.opens:
            nets = self.nets(path, pins)
            for i, a in enumerate(nets):
                for b in nets[i + 1:]:
                    boundary = None
                    if self.separating(self.isolation.find(a),
                                       self.isolation.find(b)):
                        boundary = "isolation"
                    elif a in self.ground_nets and b in self.ground_nets:
                        kinds = {self.kinds.get(a), self.kinds.get(b)}
                        if None not in kinds and len(kinds) == 2 and (
                                kinds & set(SAFETY_KINDS)):
                            boundary = (EARTH if EARTH in kinds
                                        else "chassis")
                    if boundary is not None:
                        self.report.finding(
                            "RHO4004",
                            {"component": path, "net_a": a, "net_b": b,
                             "boundary": boundary},
                            entity=path)
                        return True
        return False

    def straddles(self, path, model):
        """RHO4010 (GA-14c): a component whose pins land on ground nets of
        two ground domains no direct connection, tie or galvanic passive
        relates, inside one isolation domain. A safety capacitor's pins
        bridge without relating anything and a connector's contacts are
        transparent, so neither is counted; earth is no reference, and is
        not either."""
        passing = {pin for pair in model.bridges for pin in pair}
        passing.update(model.contacts)
        pins = [port.name for port in self.instances[path].ports
                if port.name not in passing]
        by_isolation = {}
        for net in self.nets(path, sorted(pins)):
            if net in self.ground_nets and self.kinds.get(net) != EARTH:
                by_isolation.setdefault(self.isolation.find(net),
                                        set()).add(self.ground.find(net))
        for _isolation, domains in sorted(by_isolation.items()):
            if len(domains) > 1:
                a, b = sorted(domains)[:2]
                self.report.finding(
                    "RHO4010", {"entity": path, "domain_a": a,
                                "domain_b": b},
                    entity=path)
                return

    def disjoint(self):
        """RHO4007 (GA-15): isolation domains with a fitted pin between
        which nothing crosses at all, one id for each unrelated cluster.
        A fitted part with pins in two domains relates them: a barrier
        whose sides they are, a safety capacitor, a contact."""
        clusters = _Classes(sorted({self.isolation.find(net)
                                    for net in self.live}))
        for path in self.fitted:
            roots = sorted({self.isolation.find(net) for net in self.nets(
                path, [port.name for port in self.instances[path].ports])})
            for root in roots[1:]:
                clusters.union(roots[0], root)
        ids = [members[0] for members in clusters.classes()]
        if len(ids) > 1:
            self.report.finding("RHO4007", {"domain_ids": ids}, entity="/")

    # -- the report

    def rows(self, result):
        for domain, nets in result.ground_domains.items():
            self.report.row(domain, "pass", "ground-domain", detail={
                "nets": list(nets),
                "kinds": [self.kinds.get(net) for net in nets],
                "isolation_domain": result.isolation_domain(domain)})
        for domain, nets in result.isolation_domains.items():
            if not self.live & set(nets):
                continue
            self.report.row(domain, "pass", "isolation-domain", detail={
                "nets": list(nets),
                "ground_domains": sorted({result.ground_domain(net)
                                          for net in nets
                                          if result.is_ground(net)}),
                "barriers": sorted(path for path, barriers
                                   in result.barriers().items()
                                   if any(self.isolation.find(net) == domain
                                          for _side, pins in barriers
                                          for net in self.nets(path, pins)))})
        for path, nets, how in self.bonds:
            kinds = [self.kinds.get(net) for net in nets]
            specific = {kind for kind in kinds if kind not in (None,
                                                               UNSPECIFIED)}
            if how == "galvanic" and len(specific) > 1:
                # GA section 1.4's SHOULD-level warning, uncoded by design
                # (GA notes section 5): a resistor is not a net-tie.
                self.report.row(path, "pass", "passive-joins-distinct-kinds",
                                detail={"nets": list(nets), "kinds": kinds})
        for path in self.fitted:
            for pin in self.models[path].grounds:
                net = self.model.net_of.get((path, pin))
                if net is not None and self.kinds.get(net) == "chassis":
                    # GA-10's informational note: chassis may be a
                    # reference (an automotive chassis return).
                    self.report.row(path, "pass", "chassis-as-reference",
                                    detail={"net": net})
                    break
        for path in self.model.components:
            if not self.instances[path].dnp:
                continue
            nets = self.nets(path, sorted(
                port.name for port in self.instances[path].ports))
            isolation = sorted({result.isolation_domain(net)
                                for net in nets})
            ground = sorted({result.ground_domain(net) for net in nets
                             if result.is_ground(net)})
            if len(isolation) > 1 or len(ground) > 1:
                self.report.row(path, "pass", DNP_REASON, detail={
                    "dnp": [path], "isolation_domains": isolation,
                    "ground_domains": ground})
        if not self.ground_nets and self.live:
            # GA-16 synthesizes the default ground from what the parts
            # declare; with no label, kind or `ground` rule there is none
            # to synthesize, and nothing after this pass has a reference.
            self.report.row("/", "no-data", NO_GROUND_REASON,
                            actionable=True,
                            detail={"nets": sorted(self.live)})


# A net block's head up to its attribute list: `net NAME(`, at the start
# of a line, as the grammar's net_decl writes it.
_NET_HEAD = re.compile(rb"(?m)^[ \t]*net[ \t]+([A-Za-z_][A-Za-z0-9_]*)"
                       rb"[ \t]*\(")


def _closing(data: bytes, start: int) -> int:
    """The offset of the `)` closing the attribute list opened just
    before `start`, skipping strings and comments; the end of the data
    when it has none."""
    depth, i, n = 1, start, len(data)
    while i < n:
        c = data[i:i + 1]
        if c == b'"':
            i += 1
            while i < n and data[i:i + 1] != b'"':
                i += 2 if data[i:i + 1] == b"\\" else 1
        elif c == b"#":
            while i < n and data[i:i + 1] != b"\n":
                i += 1
        elif c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n
