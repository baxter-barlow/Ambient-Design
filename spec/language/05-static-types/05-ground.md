# 05 — Static types and domains: 5 — Ground architecture

*Rhoform Language Specification · reserved · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

**Reserved for GA-1..GA-17, AMB-54 (L2c, then L3).** This section is
written in the change that implements its checker, and edited by that
change's owner alone; [section
1](../05-static-types.md#1-the-checking-model) is the model it plugs
into. It will specify GA passes 1–4 — the isolation partition, ground
typing, ground domains and the tie graph — absorbing the
ground-architecture semantics by reference, and the decisions their
implementation takes. Until it lands, the ground pass is an interim stub
that types a net as ground exactly when an author labelled it with
`ground_domain`.

Its codes are the `ground` owner's ranges (section 1, Code ranges), and
its pass is `ground`.
