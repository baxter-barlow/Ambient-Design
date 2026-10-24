# 05 — Static types and domains: 3 — Interfaces

*Rhoform Language Specification · reserved · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

**Reserved for T1, AMB-51 (L2a).** This section is written in the change
that implements its checker, and edited by that change's owner alone;
[section 1](../05-static-types.md#1-the-checking-model) is the model it
plugs into. It will specify nominal interface types and the bundles they
connect: compatibility (one definition, one shape), member-wise union,
interface parameters as expectations, and the `ref` and ground members
the ground architecture reads.

Its codes are the `interfaces` owner's ranges (section 1, Code ranges).
Section 1's pass order has no interfaces pass; where its checks run is
this section's to state.
