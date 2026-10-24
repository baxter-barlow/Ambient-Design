# 05 — Static types and domains: 6 — Voltage domains

*Rhoform Language Specification · reserved · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

**Reserved for T5, AMB-54 (L3).** This section is written in the change
that implements its checker, and edited by that change's owner alone;
[section 1](../05-static-types.md#1-the-checking-model) is the model it
plugs into. It will specify origins and their values, rails and
transfers through the component rules, envelopes, abs-max and
recommended windows evaluated as differences against the part's own
ground, domain crossings, and the current-dependent sites decided after
the budgets.

Its codes are the `domains` owner's ranges (section 1, Code ranges), and
its passes are `domains` and `domains_refine`.
