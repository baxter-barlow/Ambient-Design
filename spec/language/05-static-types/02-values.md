# 05 — Static types and domains: 2 — Values and dimensions

*Rhoform Language Specification · reserved · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

**Reserved for T3/T4, AMB-53 (the M2 landing L1c).** This section is
written in the change that implements its checker, and edited by that
change's owner alone; [section
1](../05-static-types.md#1-the-checking-model) is the model it plugs
into. It will specify the dimension of every quantity a check reads, the
exact interval algebra over the elaborated values (rational, never
through a double), the verdict a containment check reaches (inside,
outside, overlapping), the exact-value lint on part constraints, and the
dimension a constraint's name and an assertion's measurement require.
Its closed tables are reconciled where they are restated.

Its codes are the `quantities` owner's ranges (section 1, Code ranges),
and its pass is `dimensions`.
