# 05 — Static types and domains: 9 — Part data at check time

*Rhoform Language Specification · reserved · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

**Reserved for D1 and D3, AMB-59 (L2b).** This section is written in the
change that implements its checker, and edited by that change's owner
alone; [section 1](../05-static-types.md#1-the-checking-model) is the
model it plugs into. It will specify how a check reaches part data:
through the compile root's rhoform.lock and the records its picks name,
verified against the lock and joined to a definition only through the
record's `implements` map, and read honestly (a minimum or maximum is a
guarantee, a typical or peak figure never is). No part number is
searched and nothing is fetched at compile time.

Its codes are the `parts` and `lockfile` owners' ranges (section 1, Code
ranges), and its pass is `parts`.
