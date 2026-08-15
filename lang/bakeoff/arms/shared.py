"""Machinery both candidates use, so neither gets it slightly differently.

Module ordering, the L6 columnar sub-syntax, net formation from connection
statements, and the final assembly of a parsed file into a validated model all
live here. None of them is on the axis the candidates differ along, and a
second hand-written copy of any of them would put a difference into the
measurement that nobody is choosing between.

The columnar sub-syntax in particular is L6's proposal, not either
candidate's invention, so both spell it identically. That is what makes
"columnar saves N tokens" a statement about L6 rather than about A or B.
"""

from dataclasses import dataclass

from .. import library
from ..diagnostics import Diag
from ..model import (
    Assertion,
    DesignModel,
    Instance,
    ModelError,
    Module,
    Net,
    PartBinding,
    Port,
    Value,
    _resolve_endpoint,
    validate,
)
from .base import COLUMNAR_MIN_ROWS, Cursor


def module_order(model: DesignModel) -> list[Module]:
    """Definitions before their users, ties broken by name.

    Nothing in the grammar requires it — there are no imports and the parsers
    are two-pass — but a model reading the file top to bottom meets
    `LedIndicator` before `new LedIndicator`, and both arms get the same
    courtesy so it is not an axis.
    """
    ordered: list[Module] = []
    placed: set[str] = set()

    def visit(module: Module, stack: tuple[str, ...]) -> None:
        if module.name in placed:
            return
        if module.name in stack:
            # Recursive instantiation is not expressible in L1/L3, so this is
            # a corrupt model rather than a language feature. Emitting the
            # cycle instead of recursing forever keeps the failure legible.
            raise ModelError(
                "module instantiation cycle: " + " -> ".join(stack + (module.name,))
            )
        for inst in sorted(module.instances, key=lambda i: i.name):
            if inst.kind == "module":
                child = model.module(inst.definition)
                if child is not None:
                    visit(child, stack + (module.name,))
        placed.add(module.name)
        ordered.append(module)

    for module in sorted(model.modules, key=lambda m: m.name):
        visit(module, ())
    return ordered


# --------------------------------------------------------------------------
# L6 columnar
# --------------------------------------------------------------------------


@dataclass
class Table:
    definition: str
    binding: str | None
    lockfile_key: str | None
    columns: tuple[str, ...]
    rows: list

    def group_key(self) -> tuple:
        return (self.definition, self.binding, self.lockfile_key, self.columns)


def _table_shape(inst: Instance) -> Table | None:
    """The table an instance could join, or None if it cannot join one.

    An instance is only tabular when everything it carries beyond its values
    is recoverable: ports and L9 facts from the library, part constraints that
    duplicate parameters from T9-2. An instance with a `dnp` flag or a
    hand-written pin map is an exception by nature, and forcing exceptions
    into a table is how tables stop being readable.
    """
    if inst.kind != "component":
        return None
    if inst.dnp or not library.inferable_ports(inst) or not library.inferable_hardware(inst):
        return None
    binding = lockfile_key = None
    constraint_columns: list[str] = []
    if inst.part is not None:
        binding = inst.part.binding
        lockfile_key = inst.part.lockfile_key
        skip = library.inferable_constraints(inst)
        constraint_columns = sorted(set(inst.part.constraints) - skip)
    columns = tuple(sorted(inst.parameters)) + tuple(
        f"part.{name}" for name in constraint_columns
    )
    return Table(
        definition=inst.definition,
        binding=binding,
        lockfile_key=lockfile_key,
        columns=columns,
        rows=[inst],
    )


def columnar_groups(instances) -> tuple[dict, list]:
    """Split instances into columnar groups and the ones that stay statements.

    Groups keep the order of their first member so output is deterministic,
    and a group below COLUMNAR_MIN_ROWS is dissolved back into statements
    rather than being emitted as a two-row table that costs more than it saves.
    """
    tables: dict[tuple, Table] = {}
    singles: list[Instance] = []
    for inst in instances:
        shape = _table_shape(inst)
        if shape is None:
            singles.append(inst)
            continue
        key = shape.group_key()
        if key in tables:
            tables[key].rows.append(inst)
        else:
            tables[key] = shape

    kept: dict[tuple, Table] = {}
    for key, table in tables.items():
        if len(table.rows) >= COLUMNAR_MIN_ROWS:
            kept[key] = table
        else:
            singles.extend(table.rows)
    singles.sort(key=lambda i: i.name)
    return kept, singles


def _row_cells(table: Table, inst: Instance) -> list[str]:
    cells = [inst.name]
    for column in table.columns:
        if column.startswith("part."):
            cells.append(inst.part.constraints[column[5:]].render())
        else:
            cells.append(inst.parameters[column].render())
    return cells


def render_table_header(table: Table) -> str:
    if table.binding == "resolved":
        binding = f' part "{table.lockfile_key}"'
    elif table.binding == "abstract":
        binding = " part abstract"
    else:
        binding = ""
    return f"table {table.definition}{binding} ({', '.join(table.columns)}):"


def table_body(table: Table) -> list[str]:
    """Rows with columns padded to a common width.

    The padding is counted in the measurement like everything else. Alignment
    is the readability argument for L6, so measuring an unaligned table would
    be measuring something L6 did not propose.
    """
    grid = [_row_cells(table, inst) for inst in sorted(table.rows, key=lambda i: i.name)]
    widths = [max(len(row[i]) for row in grid) for i in range(len(grid[0]))]
    return [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
        for row in grid
    ]


def render_table(table: Table, indent: str) -> list[str]:
    return [indent + render_table_header(table)] + [
        indent + "    " + line for line in table_body(table)
    ]


def parse_table_header(cursor: Cursor) -> Table:
    cursor.advance()  # `table`
    definition = cursor.qualified_name("a definition name")
    binding = lockfile_key = None
    if cursor.at_keyword("part"):
        cursor.advance()
        if cursor.at_keyword("abstract"):
            cursor.advance()
            binding = "abstract"
        else:
            token = cursor.expect("STRING", what="as the pinned lockfile key")
            binding, lockfile_key = "resolved", token.text
    cursor.expect("OP", "(", what="around the column list")
    columns: list[str] = []
    if not cursor.at("OP", ")"):
        while True:
            name = cursor.expect_name("a column name")
            if cursor.at("OP", "."):
                cursor.advance()
                name = f"{name}.{cursor.expect_name('a constraint name')}"
            columns.append(name)
            if cursor.at("OP", ","):
                cursor.advance()
                continue
            break
    cursor.expect("OP", ")", what="around the column list")
    if len(set(columns)) != len(columns):
        cursor.error("0401", "a column is named twice in this table")
        cursor.fail()
    return Table(
        definition=definition,
        binding=binding,
        lockfile_key=lockfile_key,
        columns=tuple(columns),
        rows=[],
    )


def parse_table_rows(cursor: Cursor, header: Table) -> list[tuple[str, list[Value]]]:
    cursor.expect_block(f"table {header.definition}")
    rows: list[tuple[str, list[Value]]] = []
    while not cursor.at("DEDENT") and not cursor.at("EOF"):
        cursor.skip_newlines()
        if cursor.at("DEDENT") or cursor.at("EOF"):
            break
        name = cursor.expect_name("a row's instance name")
        values = [cursor.value(f"{name}.{column}") for column in header.columns]
        if not cursor.at("NEWLINE"):
            cursor.error(
                "0402",
                f"row {name!r} has more values than the table has columns "
                f"({len(header.columns)})",
                fixit="every row carries exactly one value per column",
                columns=len(header.columns),
            )
            cursor.fail()
        cursor.expect_newline()
        rows.append((name, values))
    cursor.end_block()
    if len(rows) < COLUMNAR_MIN_ROWS:
        cursor.error(
            "0403",
            f"a table needs at least {COLUMNAR_MIN_ROWS} rows, found {len(rows)}",
            fixit="write these as ordinary statements instead",
            rows=len(rows),
        )
        cursor.fail()
    return rows


# --------------------------------------------------------------------------
# Net formation
# --------------------------------------------------------------------------


def union_find_nets(builder, cursor: Cursor, code_prefix: str) -> list[Net]:
    """Turn `~` statements and signal declarations into nets.

    A net is an equivalence class of endpoints, so this is a union-find and
    not a list: `a ~ b` followed by `b ~ c` is one three-member net in both
    candidates, and any other reading would make connectivity depend on the
    order the author wrote the statements in.
    """
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    def node_for(ref: str) -> str:
        if "." not in ref and ref in builder.signals:
            return f"signal:{ref}"
        return f"port:{ref}"

    for name in builder.signals:
        find(f"signal:{name}")
    for left, right in builder.links:
        union(node_for(left), node_for(right))

    groups: dict[str, list[str]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)

    nets: list[Net] = []
    for members in groups.values():
        labels = sorted(n[len("signal:"):] for n in members if n.startswith("signal:"))
        ports = sorted(n[len("port:"):] for n in members if n.startswith("port:"))
        if len(labels) > 1:
            cursor.diagnostics.append(
                Diag(
                    code=f"{code_prefix}0211",
                    message=(
                        "one net carries two labels: "
                        + ", ".join(labels)
                        + ". Joining two named signals makes them one net, which "
                        "has no defined name."
                    ),
                    params={"labels": labels},
                    fixit="use one label, or keep the signals apart",
                )
            )
            cursor.fail()
        if not ports:
            cursor.diagnostics.append(
                Diag(
                    code=f"{code_prefix}0212",
                    message=f"signal {labels[0]!r} is declared but never connected",
                    params={"signal": labels[0]},
                    fixit="attach an endpoint to it, or delete it",
                )
            )
            cursor.fail()
        label = labels[0] if labels else None
        attributes = builder.signals.get(label, {}) if label else {}
        nets.append(
            Net(
                name=label,
                members=tuple(ports),
                ground_domain=attributes.get("ground_domain"),
                voltage_domain=attributes.get("voltage_domain"),
            )
        )
    return sorted(nets, key=lambda n: n.sort_key())


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def build_model(
    *, cursor: Cursor, builders, assertions, root_assertions, infer: bool, code_prefix: str
) -> DesignModel:
    """Assemble parsed builders into a validated model, or fail with diagnostics."""
    module_names = {b.name for b in builders}
    if len(module_names) != len(builders):
        cursor.diagnostics.append(
            Diag(
                code=f"{code_prefix}0301",
                message="two modules share a name",
                params={},
            )
        )
        cursor.fail()

    modules: list[Module] = []
    instantiated: set[str] = set()

    for builder in builders:
        instances: list[Instance] = []
        for raw in builder.instances.values():
            kind = "module" if raw["definition"] in module_names else "component"
            if kind == "module":
                instantiated.add(raw["definition"])
            part = None
            # `abstract` is tracked separately from "has constraints": once
            # T9-2 recovers every constraint an abstract part carried, the
            # rendered source has nothing left but the binding itself, and
            # inferring "no part at all" from that silence would drop the
            # binding on exactly the parts inference works best on.
            if raw["lockfile_key"] or raw["constraints"] or raw.get("abstract"):
                part = PartBinding(
                    binding="resolved" if raw["lockfile_key"] else "abstract",
                    constraints=dict(raw["constraints"]),
                    lockfile_key=raw["lockfile_key"],
                )
            inst = Instance(
                name=raw["name"],
                kind=kind,
                definition=raw["definition"],
                parameters=dict(raw["parameters"]),
                ports=tuple(sorted(raw["ports"], key=lambda p: p.name)),
                part=part,
                hardware_kind=raw["hardware_kind"],
                dnp=raw["dnp"],
                exclude_from_bom=raw["exclude_from_bom"],
                board_only=raw["board_only"],
            )
            if infer and kind == "component":
                try:
                    inst = library.apply_inference(inst)
                except library.LibraryError as exc:
                    cursor.diagnostics.append(
                        Diag(
                            code=f"{code_prefix}0302",
                            message=str(exc),
                            params={"definition": raw["definition"]},
                        )
                    )
                    cursor.fail()
            instances.append(inst)

        modules.append(
            Module(
                name=builder.name,
                qualified_name=_qualified(builder.name, instances, builders),
                ports=tuple(sorted(builder.ports, key=lambda p: p.name)),
                instances=tuple(sorted(instances, key=lambda i: i.name)),
                nets=tuple(union_find_nets(builder, cursor, code_prefix)),
            )
        )

    # Resolve every endpoint HERE, where the parser's spans are still around.
    # `validate` catches the same errors, but it works on a model and has no
    # idea which byte of source produced it — and P2 makes "which line" the
    # number this bake-off is really collecting.
    for module, builder in zip(modules, builders):
        for net in module.nets:
            label = net.name or "unlabelled"
            for ref in net.members:
                try:
                    _resolve_endpoint(
                        DesignModel(
                            design_id="",
                            root_module=modules[0].name,
                            modules=tuple(modules),
                        ),
                        module,
                        ref,
                        f"{module.name} net {label}",
                    )
                except ModelError as exc:
                    cursor.diagnostics.append(
                        Diag(
                            code=f"{code_prefix}0306",
                            message=str(exc),
                            span=getattr(builder, "spans", {}).get(ref),
                            params={"endpoint": ref, "net": label},
                        )
                    )
    if cursor.diagnostics:
        cursor.fail()

    roots = sorted(module_names - instantiated)
    if len(roots) != 1:
        cursor.diagnostics.append(
            Diag(
                code=f"{code_prefix}0303",
                message=(
                    f"expected exactly one uninstantiated module to be the design "
                    f"root, found {len(roots)}: {', '.join(roots) or '(none)'}"
                ),
                params={"candidates": roots},
                fixit="a design has one top-level module",
            )
        )
        cursor.fail()
    root = roots[0]

    misplaced = sorted(name for name, items in root_assertions.items() if items and name != root)
    if misplaced:
        cursor.diagnostics.append(
            Diag(
                code=f"{code_prefix}0304",
                message=(
                    "assertions may only be declared in the root module; found some "
                    f"in {', '.join(misplaced)}"
                ),
                params={"modules": misplaced},
            )
        )
        cursor.fail()

    model = DesignModel(
        design_id="",
        root_module=root,
        modules=tuple(sorted(modules, key=lambda m: m.name)),
        assertions=tuple(sorted(assertions, key=lambda a: a.name)),
    )
    try:
        validate(model)
    except ModelError as exc:
        cursor.diagnostics.append(
            Diag(code=f"{code_prefix}0305", message=str(exc), params={})
        )
        cursor.fail()
    return model


def _qualified(name: str, instances, builders) -> str:
    """Reconstruct a module's qualified name.

    The prototypes have no import syntax — L4 owns that, and putting a
    speculative one into both candidates would measure a construct neither is
    proposing — so a module's qualified name is not recoverable from source.
    Callers that need it against an anchor take it from the model; here it
    falls back to the bare name, and `qualified_name` is excluded from model
    equality for exactly this reason.
    """
    return name
