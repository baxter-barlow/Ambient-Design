# 05 — Static types and domains: 7 — Budgets

*Rhoform Language Specification · reserved · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

**Reserved for T10, AMB-55 (L4).** This section is written in the change
that implements its checker, and edited by that change's owner alone;
[section 1](../05-static-types.md#1-the-checking-model) is the model it
plugs into. It will specify each domain's worst-case draw against its
capability, the transfer chain's limits, and what makes a budget
verifiable: a guaranteed limit proves a pass; a typical or peak figure
is at most a lower bound.

Its codes are the `budget` owner's ranges (section 1, Code ranges), and
its pass is `budget`.
