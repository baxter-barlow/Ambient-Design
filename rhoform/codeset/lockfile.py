"""Lockfile v0 (L2b, AMB-59): the file and its packages section (not-json,
not-canonical, version-unsupported, invalid, packages-stale,
entry-unsupported). Verifying a record a pick names is block 6, in parts.py.

Its range: RHO2070-RHO2079 (rhoform.codes.RANGES). A new code takes the next
free number in the range, and CODES stays in code order. The package layer
reports every one of them, before elaboration (spec 08, The lockfile), and
any of them stops the compilation there.
"""

from . import CodeDef

CODES: tuple[CodeDef, ...] = (
    CodeDef(
        code="RHO2070", slug="lockfile-not-json", severity="error",
        message=(
            "`rhoform.lock` cannot be read as JSON: {reason}. A lockfile "
            "is strict UTF-8 JSON, with no key repeated in an object and "
            "no NaN or infinity."
        ),
        params=("reason",),
        rule="R14a L4",
    ),
    # Reported alone: every later span assumes the canonical layout, so a
    # file that is not in it gets this one finding and its fix-it.
    CodeDef(
        code="RHO2071", slug="lockfile-not-canonical", severity="error",
        message=(
            "`rhoform.lock` is not in canonical layout from line {line} on: "
            "its keys sorted, a two-space indent, one member or element per "
            "line and one trailing line feed, so that one lockfile state "
            "has one byte string. The fix-it rewrites it so, changing no "
            "value."
        ),
        params=("line",),
        rule="R14a L4",
    ),
    CodeDef(
        code="RHO2072", slug="lockfile-version-unsupported", severity="error",
        message=(
            "`rhoform.lock` declares lockfile_version {version}; this "
            "toolchain reads version(s) {supported} only, and a lockfile of "
            "any other version is refused rather than read as a neighbour."
        ),
        params=("version", "supported"),
        rule="R14a L4",
    ),
    CodeDef(
        code="RHO2073", slug="lockfile-invalid", severity="error",
        message="`rhoform.lock` at `{pointer}`: {reason}.",
        params=("pointer", "reason"),
        rule="R14a L4/L5",
    ),
    # Staleness is per input file: a manifest's bytes or a package's
    # version, source or manifest moved since the section was written. The
    # archive content hash L3 also names is not built (spec 08 deviations).
    CodeDef(
        code="RHO2074", slug="lockfile-packages-stale", severity="error",
        message=(
            "the packages section of `rhoform.lock` is stale for "
            "`{subject}`: {problem}. Nothing re-resolves it silently; "
            "re-lock the workspace (R14a L3)."
        ),
        params=("subject", "problem"),
        rule="R14a L3/L5",
    ),
    # Refused rather than ignored, as `git` and `integrity` are in the
    # manifest: an entry this version cannot honour would otherwise read as
    # honoured.
    CodeDef(
        code="RHO2075", slug="lockfile-entry-unsupported", severity="error",
        message=(
            "`rhoform.lock` holds {entry} at `{pointer}`, which this "
            "toolchain cannot honour yet ({owner}); it is refused, not "
            "ignored."
        ),
        params=("pointer", "entry", "owner"),
        rule="I2/R14a L5",
    ),
)
