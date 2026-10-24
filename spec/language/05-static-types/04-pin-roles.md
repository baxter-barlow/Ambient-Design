# 05 — Static types and domains: 4 — Pin roles

*Rhoform Language Specification · reserved · CC-BY-4.0 (see
[spec/README.md](../../README.md))*

**Reserved for T2 and L9b, AMB-52 (L1b).** This section is written in
the change that implements its checker, and edited by that change's
owner alone; [section 1](../05-static-types.md#1-the-checking-model) is
the model it plugs into. It will specify the pin-role pair table over
the physical members of a net and its fold, the deviations from the
KiCad baseline (module ports excluded, root ports as terminals, ground
nets as implicit references, passive drives inputs), unconnected pins,
and the intentional single-pin net an `isolated` statement declares.

Its codes are the `erc` owner's ranges (section 1, Code ranges), and its
pass is `erc`.
