"""Command line for the bake-off.

    python3 -m bakeoff check                 structural gate; no dependencies
    python3 -m bakeoff measure [--json]      token cost, T9 and L6 readings
    python3 -m bakeoff defects               diagnostic-quality table
    python3 -m bakeoff render --arm ...      one arm's canonical source
    python3 -m bakeoff card --arm ...        one arm's A4 language card

`check` is the one `make check` runs, and it deliberately needs nothing beyond
the pinned interpreter: round-trip, cross-arm agreement, and the external
anchors are structural facts, and a gate that could not run without an
optional package would be a gate that quietly does not run.

`measure` needs the pinned tokenizer, because it produces numbers. It refuses
to substitute an approximation; `--allow-stub` exists so the plumbing can be
exercised offline, and marks every number it produces non-gating.
"""

import argparse
import json
import sys

from .arms import ARMS, arm as get_arm
from .defects import score, summarise
from .diagnostics import ParseFailure
from .elaborate import AnchorError, check_anchor
from .measure import MeasurementError, measure
from .model import ModelError, diff, load_corpus


def _check(args) -> int:
    """Everything that must be true before any number is worth reporting."""
    problems: list[str] = []
    designs = load_corpus()
    if not designs:
        problems.append("the corpus is empty; there is nothing to measure")

    checked = 0
    for design_id, model in sorted(designs.items()):
        try:
            anchor = check_anchor(model)
        except AnchorError as exc:
            problems.append(f"{design_id}: anchor: {exc}")
            anchor = None
        if anchor is None and model.anchor:
            pass
        elif anchor is None:
            problems.append(
                f"{design_id}: declares no anchor. A reference design nothing "
                "external agrees with is an opinion."
            )
        else:
            print(
                f"bakeoff: {design_id}: agrees with {anchor['anchor']} "
                f"({anchor.get('instances', '?')} instances, "
                f"{anchor.get('nets', '?')} nets, "
                f"{anchor.get('connections', '?')} connections)"
            )

        for arm in ARMS.values():
            for variant in arm.variants:
                checked += 1
                try:
                    source = arm.render(model, variant)
                except (ValueError, ModelError) as exc:
                    problems.append(f"{design_id}/{arm.key}/{variant}: render: {exc}")
                    continue
                try:
                    parsed = arm.parse(source, variant)
                except ParseFailure as failure:
                    problems.append(
                        f"{design_id}/{arm.key}/{variant}: the arm cannot parse its "
                        "own rendering: "
                        + "; ".join(d.message for d in failure.diagnostics[:3])
                    )
                    continue
                differences = diff(model, parsed)
                if differences:
                    problems.append(
                        f"{design_id}/{arm.key}/{variant}: round trip changed the "
                        "design:\n      " + "\n      ".join(differences[:6])
                    )

    if problems:
        for problem in problems:
            print(f"bakeoff: FAIL: {problem}", file=sys.stderr)
        print(f"bakeoff: {len(problems)} failure(s).", file=sys.stderr)
        return 1

    print(
        f"bakeoff: PASS: {len(designs)} design(s), {len(ARMS)} arm(s), "
        f"{checked} arm/variant cell(s) round-trip to the same model, "
        "every design agrees with its external anchor."
    )
    return 0


def _measure(args) -> int:
    try:
        report = measure(allow_stub=args.allow_stub)
    except MeasurementError as exc:
        print(f"bakeoff: FAIL: {exc}", file=sys.stderr)
        return 1

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    identity = report["tokenizer"]
    print(f"tokenizer: {identity['name']} ({identity['kind']}), "
          f"gating={identity['gating']}")
    if not report["gating"]:
        print("WARNING: these counts are NOT comparable to pinned ones and "
              "cannot satisfy any budget.")
    print()

    print(f"{'design':20} {'arm':13} {'variant':19} {'tokens':>8} {'lines':>7} {'bytes':>8}")
    print("-" * 80)
    for cell in report["cells"]:
        print(
            f"{cell['design']:20} {cell['arm']:13} {cell['variant']:19} "
            f"{cell['tokens']:>8} {cell['lines']:>7} {cell['bytes']:>8}"
        )

    print()
    print("language cards (§4 flip criterion: ~3K tokens)")
    for key, card in sorted(report["language_cards"].items()):
        verdict = "within" if card["within_3k"] else "OVER"
        print(f"  {key:13} {card['tokens']:>6} tokens  {verdict} the ~3K budget")

    print()
    print("T9 annotation tax (explicit -> inferred; lower bound)")
    for design, arms in sorted(report["readings"]["t9_annotation_tax"].items()):
        for key, values in sorted(arms.items()):
            print(
                f"  {design:20} {key:13} -{values['tax_tokens']:>6} tokens "
                f"({values['tax_fraction'] * 100:.1f}%)"
            )

    print()
    print("L6 columnar saving (inferred -> inferred+columnar)")
    for design, arms in sorted(report["readings"]["l6_columnar_saving"].items()):
        for key, values in sorted(arms.items()):
            print(
                f"  {design:20} {key:13} -{values['saving_tokens']:>6} tokens "
                f"({values['saving_fraction'] * 100:.1f}%)"
            )

    if "defects" in report:
        print()
        print("diagnostic quality on seeded defects (variant: inferred)")
        print(f"  {'arm':13} {'detected':>12} {'localised':>12} {'diags/defect':>14}")
        for key, values in sorted(report["defects"]["summary"].items()):
            detection = values["detection_rate"]
            localisation = values["localisation_rate"]
            noise = values["diagnostics_per_defect"]
            print(
                f"  {key:13} "
                f"{values['detected']}/{values['applicable']:<10} "
                f"{'-' if localisation is None else f'{localisation * 100:.0f}%':>12} "
                f"{'-' if noise is None else f'{noise:.1f}':>14}"
            )
            if values["accepted"]:
                print(f"      ACCEPTED {values['accepted']} defective design(s)")

    print()
    print(report["readings"]["note"])
    return 0


def _defects(args) -> int:
    designs = load_corpus()
    rows = [
        row
        for design_id, model in sorted(designs.items())
        for arm in ARMS.values()
        for row in score(arm, args.variant, model, design_id)
    ]
    if args.json:
        json.dump({"rows": rows, "summary": summarise(rows)}, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    print(f"{'design':20} {'arm':13} {'defect':22} {'status':14} {'line':>5} {'at':>5} {'n':>3}")
    print("-" * 88)
    for row in rows:
        print(
            f"{row['design']:20} {row['arm']:13} {row['defect']:22} "
            f"{row['status']:14} {row.get('line', '-'):>5} "
            f"{('yes' if row.get('localised') else 'no') if row['status'] == 'detected' else '-':>5} "
            f"{row.get('diagnostics', '-'):>3}"
        )
    accepted = [row for row in rows if row["status"] == "accepted"]
    if accepted:
        print()
        print(f"{len(accepted)} defective design(s) were ACCEPTED:")
        for row in accepted:
            print(f"  {row['design']}/{row['arm']}/{row['defect']}")
        return 1
    return 0


def _render(args) -> int:
    model = load_corpus()[args.design]
    sys.stdout.write(get_arm(args.arm).render(model, args.variant))
    return 0


def _card(args) -> int:
    sys.stdout.write(get_arm(args.arm).language_card())
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="bakeoff", description="The §8-Q1 syntax bake-off (AMB-32 / R5b)."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "check", help="round trip, cross-arm agreement, external anchors"
    ).set_defaults(run=_check)

    measure_parser = subparsers.add_parser("measure", help="token cost and readings")
    measure_parser.add_argument("--json", action="store_true")
    measure_parser.add_argument(
        "--allow-stub",
        action="store_true",
        help="run with the non-gating stub tokenizer when the pin is unavailable",
    )
    measure_parser.set_defaults(run=_measure)

    defects_parser = subparsers.add_parser("defects", help="diagnostic-quality table")
    defects_parser.add_argument("--variant", default="inferred")
    defects_parser.add_argument("--json", action="store_true")
    defects_parser.set_defaults(run=_defects)

    render_parser = subparsers.add_parser("render", help="print canonical source")
    render_parser.add_argument("--design", default="blinker-555")
    render_parser.add_argument("--arm", default="candidate_a")
    render_parser.add_argument("--variant", default="inferred")
    render_parser.set_defaults(run=_render)

    card_parser = subparsers.add_parser("card", help="print an A4 language card")
    card_parser.add_argument("--arm", default="candidate_a")
    card_parser.set_defaults(run=_card)

    args = parser.parse_args(argv)
    return args.run(args)
