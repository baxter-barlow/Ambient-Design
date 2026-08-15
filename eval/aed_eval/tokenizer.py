"""Pinned token counting.

TWO COUNTERS, TWO PURPOSES. Conflating them is the mistake this module
exists to prevent.

  BUDGET TOKENS — the yardstick. Used to compare candidate grammars against
  each other (§8-Q1) and to enforce the A4 ceiling of 12K tokens on the
  model-facing context. These must be reproducible offline, on any machine,
  years apart, with no API call. They come from the pinned tokenizer here.

  TRIAL TOKENS — the cost. Used for the AC5 budget of 150K tokens per
  trial. These are whatever the provider actually billed, taken from the
  API response's usage block. They are the only honest source for cost,
  and no local tokenizer should be used to estimate them.

The pinned tokenizer is a COMMON YARDSTICK, not a claim to reproduce any
particular model's tokenization. Grammar A versus grammar B is a comparison
between two numbers produced by the same ruler, which is valid whatever the
ruler is. The A4 12K ceiling is a budget set in the same units it is
measured in. Neither use requires the ruler to match the model, and
pretending otherwise would be a claim we cannot verify for a closed
tokenizer.

PINNING IS BEHAVIOURAL, NOT BY FILE HASH. A tokenizer is pinned here by a
fingerprint over its output on a fixed probe corpus, not by the checksum of
a downloaded vocabulary file. Behaviour is what actually affects a count: a
re-packaged artifact with identical behaviour should not fail the pin, and a
same-named artifact that tokenizes differently must fail it. Fingerprinting
the output catches exactly that, and needs no knowledge of any library's
cache layout.
"""

import hashlib
from dataclasses import dataclass, asdict

# Fixed probe corpus for the behavioural fingerprint. Never edit these
# strings: changing them changes every fingerprint and silently invalidates
# every recorded pin. They deliberately mix DSL-shaped text, unicode, and
# whitespace runs, since those are where tokenizers differ most.
PROBE_CORPUS = (
    "module Blinker:\n    r1 = new Resistor\n    r1.resistance = 100kohm\n",
    "power.vcc ~ u1.VCC",
    "assert frequency(out) within 0.93Hz to 1.05Hz",
    "        ",
    "\n\n\n",
    "3.3V ± 5%",
    "µA Ω °C",
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "0123456789",
    "# comment with trailing spaces    \n",
)


@dataclass(frozen=True)
class TokenizerIdentity:
    """Everything needed to decide whether two counts are comparable."""

    name: str
    kind: str
    fingerprint: str
    n_vocab: int | None
    # False means results produced with this tokenizer must never satisfy a
    # gate. Test doubles set this; the pinned tokenizer does not.
    gating: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _fingerprint(counts: list[int], name: str) -> str:
    """Stable hash over the tokenizer's behaviour on the probe corpus."""
    payload = name + "|" + ",".join(str(c) for c in counts)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PinnedTokenizerError(RuntimeError):
    """The pinned tokenizer is unavailable or does not match its pin.

    Raised rather than falling back to an approximation. A silently
    substituted tokenizer would produce numbers that look like the pinned
    ones and are not comparable to them, which is worse than no number: an
    unavailable gate is not a pass.
    """


class TiktokenTokenizer:
    """A tiktoken BPE encoding, pinned by behavioural fingerprint.

    Requires the `tiktoken` package and, on first use for a given encoding,
    network access to fetch the vocabulary (cached thereafter). That network
    dependency is acceptable here and nowhere else in AED: this is an
    offline measurement tool, not the compiler, whose hermeticity contract
    (I3) is unaffected.
    """

    def __init__(self, encoding_name: str, expected_fingerprint: str | None = None):
        try:
            import tiktoken
        except ImportError as exc:
            raise PinnedTokenizerError(
                "tiktoken is not installed, so the pinned tokenizer cannot be "
                "loaded. Install the version pinned in toolchain/versions.yaml. "
                "The harness deliberately has no approximate fallback."
            ) from exc

        try:
            self._enc = tiktoken.get_encoding(encoding_name)
        except Exception as exc:
            raise PinnedTokenizerError(
                f"could not load tiktoken encoding {encoding_name!r}: {exc}"
            ) from exc

        self.name = encoding_name
        counts = [len(self._enc.encode(text)) for text in PROBE_CORPUS]
        self.fingerprint = _fingerprint(counts, encoding_name)

        if expected_fingerprint and self.fingerprint != expected_fingerprint:
            raise PinnedTokenizerError(
                f"tokenizer {encoding_name!r} does not match its pin.\n"
                f"  expected {expected_fingerprint}\n"
                f"  observed {self.fingerprint}\n"
                "The tokenizer's behaviour changed, so counts taken with it are "
                "not comparable to previously recorded ones. Re-pin deliberately "
                "and re-measure anything the old pin produced; do not just "
                "update the constant."
            )

    def count(self, text: str) -> int:
        return len(self._enc.encode(text))

    def identity(self) -> TokenizerIdentity:
        return TokenizerIdentity(
            name=self.name,
            kind="tiktoken",
            fingerprint=self.fingerprint,
            n_vocab=getattr(self._enc, "n_vocab", None),
            gating=True,
        )


class StubTokenizer:
    """Deterministic test double. NEVER valid for gating.

    Counts whitespace-delimited words. That is not a real tokenization and
    is not meant to be; it exists so the protocol, result capture, and CLI
    can be exercised offline with no dependencies. Its identity carries
    gating=False, and `assert_gating_tokenizer` refuses any result produced
    with it, so a stub can never quietly satisfy the A4 budget or an AC5
    gate.
    """

    name = "stub-whitespace"

    def __init__(self):
        counts = [len(text.split()) for text in PROBE_CORPUS]
        self.fingerprint = _fingerprint(counts, self.name)

    def count(self, text: str) -> int:
        return len(text.split())

    def identity(self) -> TokenizerIdentity:
        return TokenizerIdentity(
            name=self.name,
            kind="stub",
            fingerprint=self.fingerprint,
            n_vocab=None,
            gating=False,
        )


def assert_gating_tokenizer(identity: TokenizerIdentity) -> None:
    """Refuse to treat a non-gating tokenizer's numbers as authoritative."""
    if not identity.gating:
        raise PinnedTokenizerError(
            f"tokenizer {identity.name!r} is marked non-gating, so results "
            "measured with it cannot satisfy the A4 budget or an AC5 gate. "
            "Load the pinned tokenizer from toolchain/versions.yaml."
        )


def a4_context_budget(
    tokenizer, parts: dict[str, str], limit: int = 12000, enforce_gating: bool = True
) -> dict:
    """Measure the A4 model-facing context against its ceiling.

    A4 makes the language card, the agent skill, and the exemplars ONE
    budget precisely so the teaching payload cannot migrate from the card
    into the skill and out of sight. This therefore reports the total and
    the per-part breakdown together: a total that passes while one part has
    quietly tripled is a fact the report should make visible.
    """
    identity = tokenizer.identity()
    if enforce_gating:
        assert_gating_tokenizer(identity)

    breakdown = {name: tokenizer.count(text) for name, text in sorted(parts.items())}
    total = sum(breakdown.values())
    return {
        "tokenizer": identity.as_dict(),
        "limit": limit,
        "total": total,
        "breakdown": breakdown,
        "headroom": limit - total,
        "passed": total <= limit,
    }
