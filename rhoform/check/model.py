"""The checked design: a read-only view every pass reads.

A pass reads the elaborated design (rhoform/elaborate.py), not the IR: the
design keeps exact Decimals where the IR has doubles, and `ir.to_ir` is a
pure total function of it, so it is exactly the IR's content (spec 05
section 1). This view adds the indexes nearly every checker wants -- which
net a port is on, which members of a net are physical, which component
ports no statement connects -- and the raw design stays at `.design`, so a
landing that adds a field to the design reads it there and never edits
this file.

Everything is built in one walk over the design's IR-sorted lists, and
every collection here is ordered the way the IR orders it, so nothing a
pass iterates depends on hash order.
"""

from dataclasses import dataclass

# The T2 pin roles, in the order lang/grammar/rhoform_syntax.py's
# CLOSED_VOCABULARIES["pin_role"] lists them. Transcribed, not imported:
# rhoform never imports lang.grammar at import time. A test
# (rhoform/tests/test_pin_roles.py) holds this to that list and to the
# PinRole enums of the IR v1 and part-data schemas.
PinRole = (
    "power_in",
    "power_out",
    "passive",
    "bidirectional",
    "open_drain",
    "open_collector",
    "tri_state",
    "input",
    "output",
    "nc",
)


@dataclass(frozen=True)
class Member:
    """One (instance path, port) node of the design. `physical` means the
    owning instance is a component; a module's port is a hierarchical node
    that joins nets across the hierarchy and is never itself a pin."""

    path: str
    port: str
    role: str
    physical: bool


@dataclass(frozen=True)
class Constraint:
    """One part constraint: its exact value and how it was written."""

    value: object
    form: str | None  # "exact" | "toleranced" | "interval" | None
    origin: str  # "literal" | "reference"
    span: object


class CheckedDesign:
    """The view. Built once per compilation; never mutated by a pass."""

    def __init__(self, design):
        self.design = design
        self.instances = {i.path: i for i in design.instances}
        self.components = tuple(path for path, i in self.instances.items()
                                if i.kind == "component")
        self.nets = {net.name: net for net in design.nets}
        self.assertions = {a.path: a for a in design.assertions}
        ports = {(i.path, port.name): port
                 for i in design.instances for port in i.ports}
        self._ports = ports
        self.net_of = {}
        self.physical_members = {}
        self.hierarchical_members = {}
        self.endpoint_spans = {}
        for net in design.nets:
            physical, hierarchical = [], []
            for path, port in net.members:
                self.net_of[(path, port)] = net.name
                member = Member(path, port, ports[(path, port)].role,
                                self.instances[path].kind == "component")
                (physical if member.physical else hierarchical).append(member)
            self.physical_members[net.name] = tuple(physical)
            self.hierarchical_members[net.name] = tuple(hierarchical)
            self.endpoint_spans.update(net.endpoint_spans)
        # Component ports no connecting statement names. An nc port must
        # not be connected, so it is never "unconnected".
        self.unconnected = tuple(
            Member(path, port.name, port.role, True)
            for path in self.components
            for port in sorted(self.instances[path].ports,
                               key=lambda p: p.name)
            if port.role != "nc" and (path, port.name) not in self.net_of)
        root = self.instances["/"]
        self.root_ports = tuple(
            Member("/", port.name, port.role, False)
            for port in sorted(root.ports, key=lambda p: p.name))
        self.isolated = frozenset(net.name for net in design.nets
                                  if net.isolated)
        self.attribute_sites = {net.name: net.attribute_sites
                                for net in design.nets}
        # Every entity with a source-map node (ir.to_source_map): what a
        # finding may be about.
        self.entities = {}
        for i in design.instances:
            self.entities[i.path] = (i.declaration, i.trace)
        for net in design.nets:
            self.entities[net.name] = (net.declaration, net.trace)
        for a in design.assertions:
            self.entities[a.path] = (a.declaration, a.trace)

    def declaration(self, entity: str):
        """The span an entity's source-map node declares it at."""
        return self.entities[entity][0]

    def entity_spans(self, entity: str) -> tuple:
        """Declaration first, then the instantiation trace innermost-first,
        as `rhoform.diagnostics.entity_spans` resolves it from the map."""
        declaration, trace = self.entities[entity]
        return (declaration,) + tuple(trace)

    def port_decl_span(self, path: str, port: str):
        """The `port`/`pin` statement declaring a port, or None."""
        return self._ports[(path, port)].declaration

    def value(self, path: str, name: str):
        """A parameter's exact elaborated value, else a part constraint's.
        Raises KeyError for a name the instance has neither of."""
        instance = self.instances[path]
        if name in instance.parameters:
            return instance.parameters[name]
        if instance.part is not None and name in instance.part.constraints:
            return instance.part.constraints[name]
        raise KeyError(f"{path} has no parameter or constraint {name!r}")

    def constraint(self, path: str, name: str) -> Constraint | None:
        """A part constraint with its authored form, origin and span."""
        part = self.instances[path].part
        if part is None or name not in part.constraints:
            return None
        site = part.sites[name]
        return Constraint(part.constraints[name], site.form, site.origin,
                          site.span)

    def bound_span(self, assertion: str):
        """The span of an assertion's bound."""
        return self.assertions[assertion].bound_span

    def static_assertions(self) -> tuple:
        """Every `static`-tier assertion, by path."""
        return tuple(a for a in self.design.assertions if a.tier == "static")

    def pinless_components(self) -> tuple[str, ...]:
        """Components with no ports that are no L9 hardware: nothing a check
        reads about connectivity can see them."""
        return tuple(path for path in self.components
                     if not self.instances[path].ports
                     and self.instances[path].hardware_kind is None)
