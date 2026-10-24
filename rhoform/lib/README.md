# rhoform/lib: the bundled standard library

Component definitions any design can name as
`rhoform.lib.<module>.<Component>`, one module per `<module>.rhoform` file,
and, in `iface.rhoform`, the standard interfaces a bundle port or a view is
typed by, `rhoform.lib.iface.<Interface>` (syntax 0.3; spec 05/03, "The
standard interfaces", says what each one is). No component here has a view
yet: a view binds an interface's members to pins, and a wrong one would type
a domain silently, so views wait for part data that agrees with them pin for
pin.
What a module may hold, when a pin carries designators, which modules a
compilation reads and how the source map lists them are normative in
[spec/language/04-elaboration.md](../../spec/language/04-elaboration.md),
"The standard library"; this file only says how to change one.

- Keep each file canonical: `python3 -m rhoform fmt rhoform/lib/` (the
  `fmt-check` target holds it so).
- `rhoform/tests/test_library.py` instantiates every definition and checks
  the rules spec 04 states, gives every interface a bundle port, and holds
  `iface.rhoform` to spec 05/03's table of the standard interfaces.
- A changed module changes the IR of every design that names it, and a
  module's bytes are part of their `source_hash`. Regenerate the benchmark
  goldens (`regenerate()` in `rhoform/tests/test_benchmarks.py`) and the
  elaboration conformance cases (`tests/conformance/check-conformance.py
  --write`), and review the diff before committing it.
