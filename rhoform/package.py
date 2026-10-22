"""The package layer (R14b): manifests, imports, and a compilation's files.

The rules are the package spec's (R14a, "Package identity and registry
rules"); spec/language/08-packages.md restates the part M1 implements and
records where M1 stops short of it. Clause ids below are that spec's.

MANIFESTS. `rhoform.toml` (§3) is read with the stdlib `tomllib` and held
to a closed schema (M1): `[package]` with `name` (N1-N4, R2), `version`
(V1, V2), `requires-rhoform` (L9 range, V8), `license` (SPDX expression
syntax), and the optional `description`, `exclude`, and
`reserved-namespace-ack`; `[deps]` of path dependencies. Every problem is a
block-2 diagnostic spanning the offending key or value: tomllib reports no
positions, so `_TomlSpans` re-scans the (already valid) document to find
them.

DEVIATIONS for milestone M1, recorded in the decision record and in spec
08: there is no lockfile (L3 is deferred to R55), so a compilation reads
path dependencies in place; `git` and bare-string dependencies, and
`integrity` (which needs the canonical archive, G8-G10), are refused with a
diagnostic rather than ignored.

IMPORTS (§7). `import Name[, Name]* from "path"`: a path beginning `./` or
`../`, or holding no `/`, is a file of the importing file's own package,
relative to the importing file (X1); any other path is
`<namespace>/<name>/<module...>`, a file of a package the importing package
lists in `[deps]` (X2). A module path names `<path>.rhoform`; the suffix may
also be written. Resolution is lexical (no symlink is followed) and never
leaves the compile root.

THE COMPILATION is the entry file plus its import closure. `load` reads
exactly that closure plus the `rhoform.toml` files that govern it (the
entry's package and its dependencies, transitively): no directory is
listed, nothing outside the compile root is opened, and nothing touches
the network. Name binding (an imported name must be defined in its file,
and must not collide with a definition or another import) is the
elaborator's, because it needs the files' definitions.
"""

from dataclasses import dataclass, field
from pathlib import Path
import os
import posixpath
import re

from .diagnostics import Diagnostics, Span, span_from_bytes

MANIFEST = "rhoform.toml"
SUFFIX = ".rhoform"
RESERVED_NAMESPACES = ("rho", "rhoform")
PACKAGE_KEYS = ("name", "version", "requires-rhoform", "license",
                "description", "exclude", "reserved-namespace-ack")
REQUIRED_PACKAGE_KEYS = ("name", "version", "requires-rhoform", "license")
DEPENDENCY_KEYS = ("version", "path", "git", "rev", "integrity")
DESCRIPTION_LIMIT = 500

_SEGMENT = re.compile(r"[a-z](?:-?[a-z0-9])*", re.ASCII)
_NUMBER = r"(?:0|[1-9][0-9]*)"
_IDENT = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER = re.compile(
    rf"({_NUMBER})\.({_NUMBER})\.({_NUMBER})"
    rf"(?:-({_IDENT}(?:\.{_IDENT})*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?", re.ASCII)
_SPDX_TOKEN = re.compile(r"\s*(\(|\)|[A-Za-z0-9.+:-]+)", re.ASCII)
_SPDX_ID = re.compile(
    r"(?:DocumentRef-[A-Za-z0-9.-]+:)?LicenseRef-[A-Za-z0-9.-]+"
    r"|[A-Za-z0-9.-]+\+?", re.ASCII)
_SPDX_DEPTH = 32
_TOML_POSITION = re.compile(
    r"\s*\((?:at line (\d+), column (\d+)|at end of document)\)\s*\Z")


# ---- versions and ranges (§2, §4.3) -----------------------------------------

def version_problem(text: str) -> str | None:
    """Why `text` is not a manifest version (V1, V2), or None."""
    match = _SEMVER.fullmatch(text)
    if match is None:
        return ("a version is SemVer 2.0.0: MAJOR.MINOR.PATCH with an "
                "optional `-pre.release`")
    if match.group(5) is not None:
        return ("build metadata (`+...`) may not appear in a manifest, "
                "because it would give one version two identities")
    return None


def _version_key(text: str) -> tuple:
    major, minor, patch, pre, _build = _SEMVER.fullmatch(text).groups()
    return int(major), int(minor), int(patch), pre


def range_problem(text: str) -> str | None:
    """Why `text` is not a version range (L9), or None. `^X.Y.Z` takes a
    release version; `=` pins any version, a pre-release included (V3)."""
    if text[:1] not in ("^", "="):
        return "a range is `^X.Y.Z` or `=X.Y.Z`, and no other operator exists"
    problem = version_problem(text[1:])
    if problem is not None:
        return problem
    if text[0] == "^" and _version_key(text[1:])[3] is not None:
        return ("a `^` range takes a release version; a pre-release is "
                "selected only when pinned with `=`")
    return None


def range_admits(text: str, version: str) -> bool:
    """Whether the (valid) range `text` admits the (valid) `version`. `^`
    is the compatibility window (`0.Y` lines are each their own window);
    a pre-release satisfies only an exact pin (V3)."""
    want = _version_key(text[1:])
    have = _version_key(version)
    if text[0] == "=":
        return want == have
    if have[3] is not None:
        return False
    if want[0] > 0:
        upper = (want[0] + 1, 0, 0)
    else:
        upper = (0, want[1] + 1, 0)
    return want[:3] <= have[:3] < upper


def language_versions() -> tuple[str, ...]:
    """The language versions this toolchain implements: each syntax
    version the grammar lists, plus `.0` (decision S-3)."""
    from .parser import syntax_versions

    return tuple(version + ".0" for version in syntax_versions())


def name_problem(name: str) -> str | None:
    """Why `name` is not a package name (N1, N2, N4), or None."""
    segments = name.split("/")
    if len(segments) != 2:
        return ("a package name is exactly two segments, `namespace/name`, "
                f"not {len(segments)}")
    for segment in segments:
        if not _SEGMENT.fullmatch(segment):
            return (f"segment `{segment}` is not lowercase letters and "
                    "digits joined by single hyphens, starting with a "
                    "letter")
        if len(segment.encode()) > 63:
            return f"segment `{segment[:16]}...` is longer than 63 bytes"
    if len(name.encode()) > 100:
        return "a package name is at most 100 bytes"
    return None


def spdx_problem(text: str) -> str | None:
    """Why `text` is not an SPDX license expression, or None. Syntax only:
    identifiers are not checked against the SPDX list, which this
    repository does not vendor."""
    tokens, position = [], 0
    text = text.rstrip()
    while position < len(text):
        match = _SPDX_TOKEN.match(text, position)
        if match is None:
            return f"`{text[position:].strip()[:20]}` is not an SPDX token"
        tokens.append(match.group(1))
        position = match.end()
    if not tokens:
        return "it is empty"
    position = 0

    def word(expected):
        nonlocal position
        if position < len(tokens) and tokens[position] == expected:
            position += 1
            return True
        return False

    def identifier():
        nonlocal position
        if position < len(tokens) \
                and tokens[position] not in ("AND", "OR", "WITH", "(", ")") \
                and _SPDX_ID.fullmatch(tokens[position]):
            position += 1
            return True
        return False

    def expression(depth):
        if depth > _SPDX_DEPTH:
            return "parentheses nest too deeply"
        while True:
            if word("("):
                problem = expression(depth + 1)
                if problem:
                    return problem
                if not word(")"):
                    return "a `(` is not closed"
            elif not identifier():
                return "a license identifier is missing"
            elif word("WITH") and not identifier():
                return "`WITH` needs an exception identifier"
            if not (word("AND") or word("OR")):
                return None

    problem = expression(0)
    if problem is None and position < len(tokens):
        problem = f"`{tokens[position]}` is out of place"
    return problem


# ---- positions in a valid TOML document --------------------------------------

class _TomlSpans:
    """Character spans of a VALID TOML document's tables, keys and values,
    by key path. tomllib has already accepted the text, so this scanner
    only has to find extents, never to judge. It is total: on anything it
    does not follow it stops, and a lookup falls back to the nearest
    enclosing thing it did see, then to the start of the file."""

    def __init__(self, text: str):
        self.text = text
        self.tables: dict[tuple, tuple[int, int]] = {}
        self.keys: dict[tuple, tuple[int, int]] = {}
        self.values: dict[tuple, tuple[int, int]] = {}
        try:
            self._document()
        except (IndexError, ValueError, RecursionError):
            pass

    def find(self, path: tuple, part: str = "value") -> tuple[int, int]:
        """The span of `path`'s value (or key), else of its nearest
        ancestor: a key's line, a table's header."""
        table = self.values if part == "value" else self.keys
        if path in table:
            return table[path]
        for depth in range(len(path), 0, -1):
            prefix = path[:depth]
            for found in (self.keys, self.tables):
                if prefix in found:
                    return found[prefix]
        return (0, 0)

    def _skip(self, position, newlines=False):
        text = self.text
        while position < len(text):
            char = text[position]
            if char in " \t" or (newlines and char in "\r\n"):
                position += 1
            elif char == "#" and newlines:
                while position < len(text) and text[position] != "\n":
                    position += 1
            else:
                break
        return position

    def _document(self):
        text, position, table = self.text, 0, ()
        while position < len(text):
            position = self._skip(position, newlines=True)
            if position >= len(text):
                break
            if text[position] == "[":
                start = position
                double = text.startswith("[[", position)
                position += 2 if double else 1
                keys, _s, _e, position = self._key(self._skip(position))
                position = self._skip(position)
                position += 2 if double else 1
                table = tuple(keys)
                self.tables.setdefault(table, (start, position))
                continue
            keys, start, end, position = self._key(position)
            path = table + tuple(keys)
            position = self._skip(position)
            if text[position] != "=":
                raise ValueError("lost the document")
            value_start = self._skip(position + 1)
            position = self._value(value_start, path)
            self.keys.setdefault(path, (start, end))
            self.values.setdefault(path, (value_start, position))

    def _key(self, position):
        """(segments, start, end, after) of a dotted key at `position`."""
        import tomllib

        text, segments, start = self.text, [], position
        while True:
            char = text[position]
            if char in "\"'":
                close = position + 1
                while text[close] != char:
                    close += 2 if char == '"' and text[close] == "\\" else 1
                raw = text[position:close + 1]
                segments.append(tomllib.loads("k = " + raw)["k"])
                position = close + 1
            else:
                end = position
                while end < len(text) and (text[end].isalnum()
                                           or text[end] in "_-"):
                    end += 1
                if end == position:
                    raise ValueError("not a key")
                segments.append(text[position:end])
                position = end
            end = position
            after = self._skip(position)
            if after < len(text) and text[after] == ".":
                position = self._skip(after + 1)
                continue
            return segments, start, end, after

    def _value(self, position, path):
        """The end of the value starting at `position`, recording the
        spans of an inline table's keys and values under `path`."""
        text = self.text
        for quote in ('"""', "'''"):
            if text.startswith(quote, position):
                close = position + 3
                while not text.startswith(quote, close):
                    close += 2 if quote[0] == '"' and text[close] == "\\" \
                        else 1
                close += 3
                while close < len(text) and text[close] == quote[0]:
                    close += 1
                return close
        char = text[position]
        if char in "\"'":
            close = position + 1
            while text[close] != char:
                close += 2 if char == '"' and text[close] == "\\" else 1
            return close + 1
        if char == "[":
            position = self._skip(position + 1, newlines=True)
            while text[position] != "]":
                position = self._value(position, None)
                position = self._skip(position, newlines=True)
                if text[position] == ",":
                    position = self._skip(position + 1, newlines=True)
            return position + 1
        if char == "{":
            position = self._skip(position + 1)
            while text[position] != "}":
                keys, start, end, position = self._key(position)
                inner = None if path is None else path + tuple(keys)
                position = self._skip(position)
                value_start = self._skip(position + 1)
                position = self._value(value_start, inner)
                if inner is not None:
                    self.keys.setdefault(inner, (start, end))
                    self.values.setdefault(inner, (value_start, position))
                position = self._skip(position)
                if text[position] == ",":
                    position = self._skip(position + 1)
            return position + 1
        end = position
        while end < len(text) and text[end] not in ",]}\r\n#":
            end += 1
        while end > position and text[end - 1] in " \t":
            end -= 1
        return end


# ---- the manifest (§3) -------------------------------------------------------

@dataclass
class Dependency:
    name: str
    root: str | None  # directory key of the dependency, when it has a path
    range: str | None  # the `version` range, when valid
    key_span: Span
    path_span: Span
    version_span: Span
    path: str = ""


@dataclass
class Package:
    """A directory governed by a rhoform.toml, or (manifest None) the
    compile root of a compilation no manifest governs."""

    root: str  # directory key, relative to the compile root ("" for it)
    manifest: str | None  # the manifest's file key
    data: bytes = b""
    name: str | None = None
    version: str | None = None
    requires: str | None = None
    requires_span: Span | None = None
    deps: dict = field(default_factory=dict)  # name -> Dependency
    broken_deps: set = field(default_factory=set)  # reported, not usable
    ok: bool = True  # compiled at all: no manifest error, range admits us

    def lacks(self) -> str:
        """Why a package import from a file of this package has no [deps]
        entry to use."""
        if self.manifest is None:
            return "no rhoform.toml governs the importing file"
        return f"package `{self.name}` does not list it in [deps]"


def _kind(value) -> str:
    """How a TOML value is named in a diagnostic."""
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, str):
        return f"the string `{value[:40]}`"
    if isinstance(value, int):
        return "an integer"
    if isinstance(value, float):
        return "a float"
    if isinstance(value, dict):
        return "a table"
    if isinstance(value, list):
        return "an array"
    return "a date or time"


def _join(directory: str, relative: str) -> str:
    """A directory key joined with a relative POSIX path, normalized
    lexically. The compile root is "", and a key outside it starts `..`."""
    joined = posixpath.normpath(posixpath.join(directory or ".", relative))
    return "" if joined == "." else joined


def _outside(key: str, root: str) -> bool:
    """Whether the key lies outside the directory key `root`."""
    if key == ".." or key.startswith("../") or key.startswith("/"):
        return True
    return bool(root) and key != root and not key.startswith(root + "/")


def read_manifest(package: Package, sink: Diagnostics) -> None:
    """Parse and check `package.data` as its rhoform.toml, filling the
    package in. Every problem is reported; `ok` ends False if any was."""
    import tomllib

    file, data = package.manifest, package.data
    before = sink.counts()["error"]

    def span(chars):
        start, end = chars
        return span_from_bytes(file, data, len(text[:start].encode()),
                               len(text[:end].encode()))

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        package.ok = False
        sink.add("RHO2048", {"reason": "it is not UTF-8"},
                 primary=span_from_bytes(file, data, exc.start, exc.start))
        return
    try:
        document = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError) as exc:
        package.ok = False
        message = str(exc) if isinstance(exc, tomllib.TOMLDecodeError) \
            else "it nests too deeply"
        where = _TOML_POSITION.search(message)
        reason, offset = message, len(text)
        if where is not None:
            reason = message[:where.start()]
            if where.group(1) is not None:
                line, column = int(where.group(1)), int(where.group(2))
                starts = [0] + [i + 1 for i, c in enumerate(text)
                                if c == "\n"]
                offset = min(starts[min(line, len(starts)) - 1] + column - 1,
                             len(text))
        end = text.find("\n", offset)
        end = len(text) if end < 0 else end
        sink.add("RHO2048", {"reason": reason[:1].lower() + reason[1:]},
                 primary=span((offset, max(offset, end))))
        return
    spans = _TomlSpans(text)

    def at(path, part="value"):
        return span(spans.find(path, part))

    def invalid(path, expected, value):
        sink.add("RHO2051", {"key": ".".join(path), "expected": expected,
                             "found": _kind(value)}, primary=at(path))

    for key in document:
        if key not in ("package", "deps"):
            sink.add("RHO2049", {"key": key, "where": "at the top level"},
                     primary=at((key,), "key"))
    table = document.get("package")
    if table is None:
        sink.add("RHO2050", {"table": "the manifest", "key": "package"},
                 primary=span_from_bytes(file, data, 0, 0))
        table = {}
    elif not isinstance(table, dict):
        invalid(("package",), "a table", table)
        table = {}
    for key in table:
        if key not in PACKAGE_KEYS:
            sink.add("RHO2049", {"key": key, "where": "in [package]"},
                     primary=at(("package", key), "key"))
    for key in REQUIRED_PACKAGE_KEYS:
        if key not in table and "package" in document:
            sink.add("RHO2050", {"table": "[package]", "key": key},
                     primary=at(("package",), "key"))

    def string(key):
        value = table.get(key)
        if value is not None and not isinstance(value, str):
            invalid(("package", key), "a string", value)
            return None
        return value

    ack = table.get("reserved-namespace-ack")
    if ack is not None and not isinstance(ack, bool):
        invalid(("package", "reserved-namespace-ack"), "a boolean", ack)
    name = string("name")
    if name is not None:
        problem = name_problem(name)
        if problem is not None:
            sink.add("RHO2052", {"name": name, "reason": problem},
                     primary=at(("package", "name")))
        else:
            package.name = name
            namespace = name.split("/")[0]
            if namespace in RESERVED_NAMESPACES and ack is not True \
                    and not (ack is not None and not isinstance(ack, bool)):
                sink.add("RHO2055", {"name": name, "namespace": namespace},
                         primary=at(("package", "name")))
    version = string("version")
    if version is not None:
        problem = version_problem(version)
        if problem is not None:
            sink.add("RHO2053", {"version": version, "reason": problem},
                     primary=at(("package", "version")))
        else:
            package.version = version
    requires = string("requires-rhoform")
    if requires is not None:
        problem = range_problem(requires)
        if problem is not None:
            sink.add("RHO2054", {"range": requires, "reason": problem},
                     primary=at(("package", "requires-rhoform")))
        else:
            package.requires = requires
            package.requires_span = at(("package", "requires-rhoform"))
    license_ = string("license")
    if license_ is not None:
        problem = spdx_problem(license_)
        if problem is not None:
            sink.add("RHO2051", {"key": "package.license",
                                 "expected": "an SPDX license expression",
                                 "found": f"`{license_[:40]}` ({problem})"},
                     primary=at(("package", "license")))
    description = string("description")
    if description is not None \
            and len(description.encode()) > DESCRIPTION_LIMIT:
        sink.add("RHO2051", {"key": "package.description",
                             "expected": f"at most {DESCRIPTION_LIMIT} bytes",
                             "found": f"{len(description.encode())} bytes"},
                 primary=at(("package", "description")))
    exclude = table.get("exclude")
    if exclude is not None and not (
            isinstance(exclude, list)
            and all(isinstance(item, str) for item in exclude)):
        invalid(("package", "exclude"), "an array of strings", exclude)

    deps = document.get("deps", {})
    if not isinstance(deps, dict):
        invalid(("deps",), "a table", deps)
        deps = {}
    for dep_name, value in deps.items():
        _read_dependency(package, dep_name, value, at, invalid, sink)

    if sink.counts()["error"] > before:
        package.ok = False
        return
    supported = language_versions()
    if not any(range_admits(package.requires, v) for v in supported):
        package.ok = False
        sink.add("RHO2058", {"package": package.name,
                             "range": package.requires,
                             "supported": ", ".join(supported)},
                 primary=package.requires_span)


def _read_dependency(package, dep_name, value, at, invalid, sink) -> None:
    path = ("deps", dep_name)
    problem = name_problem(dep_name)
    if problem is not None:
        sink.add("RHO2052", {"name": dep_name, "reason": problem},
                 primary=at(path, "key"))
        return
    if isinstance(value, str):
        sink.add("RHO2056", {
            "package": dep_name,
            "problem": "is a bare version string; a dependency is an "
                       "inline table with a `version` range and a `path` "
                       "(R14a M2)"}, primary=at(path))
        return
    if not isinstance(value, dict):
        invalid(path, "an inline table", value)
        return
    clean = True
    for key in value:
        if key not in DEPENDENCY_KEYS:
            clean = False
            sink.add("RHO2049", {"key": key,
                                 "where": f"in dependency `{dep_name}`"},
                     primary=at(path + (key,), "key"))
    for key, problem in (
        ("git", "has a `git` source, which this toolchain does not read "
                "yet: only `path` dependencies compile until the lockfile "
                "lands (R55)"),
        ("integrity", "states `integrity`, which nothing can verify until "
                      "the lockfile and the canonical archive land (R55)"),
    ):
        if key in value:
            clean = False
            sink.add("RHO2056", {"package": dep_name, "problem": problem},
                     primary=at(path + (key,), "key"))
    if "rev" in value and "git" not in value:
        clean = False
        sink.add("RHO2056", {"package": dep_name,
                             "problem": "states `rev` without a `git` "
                                        "source (R14a M3)"},
                 primary=at(path + ("rev",), "key"))
    if "path" not in value and "git" not in value:
        clean = False
        sink.add("RHO2056", {"package": dep_name,
                             "problem": "declares no `path`; every "
                                        "dependency names its source "
                                        "(R14a M2)"},
                 primary=at(path, "key"))
    dependency = Dependency(dep_name, None, None, at(path, "key"),
                            at(path + ("path",)), at(path + ("version",)))
    version = value.get("version")
    if version is None:
        clean = False
        sink.add("RHO2050", {"table": f"dependency `{dep_name}`",
                             "key": "version"}, primary=at(path, "key"))
    elif not isinstance(version, str):
        clean = False
        invalid(path + ("version",), "a string", version)
    elif range_problem(version) is not None:
        clean = False
        sink.add("RHO2054", {"range": version,
                             "reason": range_problem(version)},
                 primary=at(path + ("version",)))
    else:
        dependency.range = version
    where = value.get("path")
    if where is not None and not isinstance(where, str):
        clean = False
        invalid(path + ("path",), "a string", where)
    elif where is not None:
        dependency.path = where
        root = _join(package.root, where) if not where.startswith("/") \
            else where
        if where.startswith("/") or _outside(root, ""):
            clean = False
            sink.add("RHO2057", {
                "package": dep_name, "path": where,
                "problem": "lies outside the compile root, so its files "
                           "cannot be named; compile from a root that "
                           "holds both packages"},
                primary=at(path + ("path",)))
        else:
            dependency.root = root
    if clean:
        package.deps[dep_name] = dependency


# ---- import paths (§7) -------------------------------------------------------

@dataclass(frozen=True)
class Import:
    """One import statement of a file, resolved. `target` is the file key
    it names, or None when resolving it failed (already reported)."""

    path: str  # the string, unquoted
    path_span: Span
    names: tuple  # ((name, Span), ...), source order
    target: str | None


def _module_file(segments) -> str:
    joined = "/".join(segments)
    return joined if joined.endswith(SUFFIX) else joined + SUFFIX


def classify(text: str):
    """("local", relative path) for X1, ("package", name, module path) for
    X2, or ("invalid", reason). Lexical only: nothing is read."""
    if not text:
        return "invalid", "it is empty"
    if text.startswith("/"):
        return "invalid", "an absolute path names no file of any package"
    segments = text.split("/")
    if "" in segments:
        return "invalid", "it has an empty segment"
    local = text.startswith("./") or text.startswith("../") or len(
        segments) == 1
    if segments[-1] in (".", ".."):
        return "invalid", f"`{segments[-1]}` names a directory, not a file"
    if local:
        return "local", _module_file(segments)
    name = "/".join(segments[:2])
    problem = name_problem(name)
    if problem is not None:
        return "invalid", (f"it is not `./`-relative, so `{name}` must be "
                           f"a package name, and {problem}")
    if len(segments) == 2:
        return "invalid", (f"it names the package `{name}` but no module "
                           "in it")
    if any(segment in (".", "..") for segment in segments[2:]):
        return "invalid", ("a package import's module path may not hold "
                           "`.` or `..`")
    return "package", name, _module_file(segments[2:])


class Resolver:
    """Import strings to file keys. `exists(key)` and `owner(key)` (the
    directory key of the package a file belongs to) are the only questions
    it asks of the file system, so `link` can run it over files already in
    hand and `load` over the disk."""

    def __init__(self, sink, exists, owner, package_of):
        self.sink = sink
        self.exists = exists
        self.owner = owner
        self.package_of = package_of  # directory key -> Package

    def resolve(self, importer: str, text: str, span: Span) -> str | None:
        package = self.package_of(self.owner(importer))
        kind, *rest = classify(text)
        if kind == "invalid":
            self.sink.add("RHO2062", {"path": text, "reason": rest[0]},
                          primary=span)
            return None
        if kind == "local":
            target = _join(posixpath.dirname(importer), rest[0])
            root, boundary = package.root, (
                "the compile root" if package.manifest is None
                else f"package `{package.name}`")
        else:
            name, module = rest
            dependency = package.deps.get(name)
            if dependency is None:
                if name in package.broken_deps:
                    return None  # its declaration was already reported
                self.sink.add("RHO2063", {"path": text, "package": name,
                                          "reason": package.lacks()},
                              primary=span)
                return None
            dep_package = self.package_of(dependency.root)
            if dep_package is None or not dep_package.ok:
                return None  # the dependency's own defect is reported
            target = _join(dependency.root, module)
            root, boundary = dependency.root, f"package `{name}`"
        if _outside(target, root) or self.owner(target) != root:
            self.sink.add("RHO2061", {"path": text, "boundary": boundary},
                          primary=span)
            return None
        if not self.exists(target):
            self.sink.add("RHO2060", {"path": text, "file": target},
                          primary=span)
            return None
        return target


def import_statements(result) -> list:
    """(path text, path span, ((name, span), ...)) per import statement of
    an `ok` parse result, in source order."""
    found = []
    for node in result.tree.children:
        if not (hasattr(node, "children") and node.data == "import_stmt"):
            continue
        string = node.children[-1]
        names = tuple((str(child), result.span_of(child))
                      for child in node.children
                      if getattr(child, "type", None) == "FREE_NAME")
        found.append((str(string)[1:-1], result.span_of(string), names))
    return found


def report_cycles(imports: dict, order: list, sink: Diagnostics) -> bool:
    """Report each import cycle once, at the first of its import
    statements by file path and position, naming its files in path order;
    True when any exists. Nothing depends on which file was the entry, so
    two compilations of one run that meet one cycle report it alike.
    Iterative, so a long chain cannot exhaust the stack."""
    rank = {key: position for position, key in enumerate(order)}
    edges = {key: [i.target for i in imports.get(key, ())
                   if i.target is not None and i.target in rank]
             for key in order}
    index, low, on_stack, stack, components = {}, {}, set(), [], []
    counter = 0
    for start in order:
        if start in index:
            continue
        work = [(start, 0)]
        while work:
            node, position = work.pop()
            if position == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            if position < len(edges[node]):
                work.append((node, position + 1))
                target = edges[node][position]
                if target not in index:
                    work.append((target, 0))
                elif target in on_stack:
                    low[node] = min(low[node], index[target])
                continue
            for target in edges[node]:
                if target in on_stack:
                    low[node] = min(low[node], low[target])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
    found = False
    for component in components:
        members = set(component)
        closing = [(key, i.path_span.byte_start, i.path_span)
                   for key in component for i in imports.get(key, ())
                   if i.target in members]
        if not closing:
            continue
        found = True
        closing.sort(key=lambda item: (item[0], item[1]))
        sink.add("RHO2064", {"cycle": sorted(component)},
                 primary=closing[0][2],
                 secondary=tuple((span, "also part of the cycle")
                                 for _r, _b, span in closing[1:]))
    return found


def link(results, sink: Diagnostics) -> dict:
    """Resolve the imports of files already parsed, with nothing read: the
    files of the compilation are exactly `results`, no manifest governs
    them, and their compile root is their common root. This is what
    `elaborate()` does for a caller that brings its own files; the command
    line goes through `load`, which reads the import closure."""
    keys = {result.file for result in results}
    loose = Package(root="", manifest=None)
    resolver = Resolver(sink, keys.__contains__, lambda _key: "",
                        lambda _root: loose)
    imports = {}
    for result in results:
        imports[result.file] = [
            Import(text, span, names, resolver.resolve(result.file, text,
                                                       span))
            for text, span, names in import_statements(result)]
    report_cycles(imports, [result.file for result in results], sink)
    return imports


# ---- loading a compilation from disk -----------------------------------------

class ReadFailure(Exception):
    """A file the compilation needs exists but could not be read: an
    operational failure (exit 2), not a diagnostic."""

    def __init__(self, path: Path, error: OSError):
        super().__init__(f"cannot read {path}: {error}")
        self.path = path


@dataclass
class Compilation:
    results: list  # ParseResult, the entry first, then in load order
    imports: dict  # file key -> [Import]
    ok: bool  # nothing the package layer reported stops elaboration


def _is_file(path: Path) -> bool:
    """Whether `path` is a regular file. Never raises: a name the file
    system cannot hold (too long, say) is no file, where Python 3.12's
    Path.is_file() raised."""
    return os.path.isfile(path)


class _Loader:
    def __init__(self, root: Path, sink: Diagnostics):
        self.root = root
        self.sink = sink
        self.owners: dict[str, str] = {}
        self.packages: dict[str, Package] = {}
        self.expanded: set[str] = set()  # packages whose deps are checked
        self.sources: dict[str, str] = {}  # package name -> its root

    def disk(self, key: str) -> Path:
        return self.root / key if key else self.root

    def owner(self, key: str) -> str:
        """The directory key of the package `key` belongs to: the nearest
        directory from the file's own up to the compile root holding a
        rhoform.toml, else the compile root itself."""
        directory = posixpath.dirname(key)
        if directory in self.owners:
            return self.owners[directory]
        walk = directory
        while True:
            if _is_file(self.disk(walk) / MANIFEST):
                found = walk
                break
            if not walk:
                found = ""
                break
            walk = posixpath.dirname(walk)
        self.owners[directory] = found
        return found

    def read(self, key: str) -> bytes:
        path = self.disk(key)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ReadFailure(path, exc) from None

    def manifest(self, root: str) -> Package:
        """The package whose rhoform.toml is in directory `root`, its
        manifest read and checked once."""
        if root not in self.packages:
            key = posixpath.join(root, MANIFEST) if root else MANIFEST
            package = Package(root=root, manifest=key, data=self.read(key))
            self.packages[root] = package
            read_manifest(package, self.sink)
            if package.name is not None:
                self.sources.setdefault(package.name, root)
        return self.packages[root]

    def package(self, root: str) -> Package:
        """The package rooted at directory key `root`, with every
        dependency it reaches checked (manifests only: a dependency's
        files are read when something imports them)."""
        if root in self.packages and root in self.expanded:
            return self.packages[root]
        if not _is_file(self.disk(root) / MANIFEST):
            self.packages[root] = Package(root=root, manifest=None)
            self.expanded.add(root)
            return self.packages[root]
        work = [root]
        while work:
            current = work.pop(0)
            if current in self.expanded:
                continue
            self.expanded.add(current)
            package = self.manifest(current)
            for dependency in list(package.deps.values()):
                if self.check_dependency(dependency):
                    work.append(dependency.root)
                else:
                    del package.deps[dependency.name]
                    package.broken_deps.add(dependency.name)
        return self.packages[root]

    def check_dependency(self, dependency) -> bool:
        """The path dependency names a package root holding the package it
        claims, at a version its range admits, from one source only, and
        that package compiles."""

        def wrong(problem, span):
            self.sink.add("RHO2057", {"package": dependency.name,
                                      "path": dependency.path,
                                      "problem": problem}, primary=span)
            return False

        root = dependency.root
        if not _is_file(self.disk(root) / MANIFEST):
            return wrong("holds no rhoform.toml, so it is not a package",
                         dependency.path_span)
        claimed = self.sources.get(dependency.name)
        if claimed is not None and claimed != root:
            return wrong(f"is a second source for a package already read "
                         f"from `{claimed or '.'}`; one package has one "
                         "source", dependency.path_span)
        self.sources[dependency.name] = root
        target = self.manifest(root)
        if target.name is not None and target.name != dependency.name:
            return wrong(f"is the package `{target.name}`",
                         dependency.key_span)
        if target.version is not None and dependency.range is not None \
                and not range_admits(dependency.range, target.version):
            return wrong(f"is version {target.version}, outside "
                         f"`{dependency.range}`", dependency.version_span)
        return target.ok

    def load(self, entry: str, parse) -> Compilation:
        before = self.sink.counts()["error"]
        resolver = Resolver(self.sink, lambda key: _is_file(self.disk(key)),
                            self.owner, self.packages.get)
        results, imports, order, queued = [], {}, [], {entry}
        work = [entry]
        refused = False
        while work:
            key = work.pop(0)
            package = self.package(self.owner(key))
            if not package.ok:
                refused = True
                continue
            result = parse(self.read(key).decode("utf-8", "surrogateescape"),
                           key)
            self.sink.extend(result.diagnostics)
            results.append(result)
            order.append(key)
            if not result.ok:
                continue
            if not self.contained(package, result):
                continue
            found = []
            for text, span, names in import_statements(result):
                target = resolver.resolve(key, text, span)
                found.append(Import(text, span, names, target))
                if target is not None and target not in queued:
                    queued.add(target)
                    work.append(target)
            imports[key] = found
        report_cycles(imports, order, self.sink)
        ok = not refused and self.sink.counts()["error"] == before
        return Compilation(results, imports, ok)

    def contained(self, package: Package, result) -> bool:
        """V9/V10: the file's language version lies in its package's
        `requires-rhoform`."""
        if package.requires is None:
            return True
        pragma = next(child for child in result.tree.children
                      if getattr(child, "type", None) == "PRAGMA")
        version = str(pragma).split()[-1] + ".0"
        if range_admits(package.requires, version):
            return True
        self.sink.add("RHO2059", {
            "file": result.file, "version": version,
            "range": package.requires, "package": package.name,
            "supported": ", ".join(language_versions())},
            primary=result.span_of(pragma),
            secondary=((package.requires_span, "the package's range"),))
        return False


def load(entry: str, root: Path, sink: Diagnostics) -> Compilation:
    """Read and parse the compilation whose entry file is `entry` (its key,
    relative to the compile root `root`): the entry, its import closure,
    and the manifests that govern them. Every problem is reported into
    `sink`; `ok` is False when elaboration must not run. Raises
    ReadFailure when a file that exists cannot be read."""
    from .parser import parse

    def parse_one(source, key):
        return parse(source, file=key)

    return _Loader(Path(root), sink).load(entry, parse_one)
