# 05 — Static types and domains: 8 — Waivers and static assertions

*Rhoform Language Specification · reserved · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

**Reserved for T6 and V1, AMB-56 (L5a).** This section is written in the
change that implements its checker, and edited by that change's owner
alone; [section 1](../05-static-types.md#1-the-checking-model) is the
model it plugs into. It will specify per-site waivers with their
justification, applied before deduplication and surfaced in the stream
and the report, and the static assertion tier's evaluation rules and
results. Until it lands, every declared static-tier assertion is RHO3553
(section 1).

Its codes are the `waivers` owner's ranges (section 1, Code ranges), and
its pass is `assertions`.
