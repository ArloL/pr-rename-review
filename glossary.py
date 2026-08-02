"""Apply a rename glossary to text.

The vocabulary comes from `.pr-rename-review.toml`; only the logic lives here.
Normalization runs in two passes: an ordered whole-word pass, then a
component-level pass that splits identifiers on camel/snake boundaries and
maps each part through the same vocabulary. The second pass exists because a
compound the design doc never spells out (`AusschreibungPersistenceTest`,
`duplikatRepository`) would otherwise survive and read as a naming decision
when it is really the same mechanical substitution one level down.
"""
import re

IDENT = re.compile(r"[A-Za-z0-9_]+")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+|_+")


class GlossaryError(Exception):
    pass


def _lower1(s):
    return s[0].lower() + s[1:]


def _recase(part, repl):
    if part.isupper() and len(part) > 1:
        return repl.upper()
    if part[:1].islower():
        return repl[0].lower() + repl[1:]
    return repl


class Glossary:
    def __init__(self, rules, parts):
        self._rules = rules
        self._parts = parts

    def _map_ident(self, m):
        tok = m.group(0)
        parts = CAMEL.findall(tok)
        if len(parts) < 2:
            return tok
        out, hit = [], False
        for p in parts:
            r = self._parts.get(p.lower())
            if r and p != "_":
                out.append(_recase(p, r))
                hit = True
            else:
                out.append(p)
        return "".join(out) if hit else tok

    def normalize(self, text):
        for pat, repl in self._rules:
            text = pat.sub(repl, text)
        return IDENT.sub(self._map_ident, text)


def _compile_rules(tables):
    rules = []
    for k, v in tables.classes.items():
        rules.append((k, v))
        rules.append((_lower1(k), _lower1(v)))
    for k, v in tables.words.items():
        rules.append((k, v))
        rules.append((_lower1(k), _lower1(v)))
        rules.append((k.upper(), v.upper()))
    for k, v in tables.columns.items():
        rules.append((k, v))
        rules.append((k.upper(), v.upper()))
    # Longest source first, so TenderDuplicateRepository wins over Tender.
    # sorted() is stable, so equal-length keys keep table precedence:
    # classes, then words, then columns.
    rules.sort(key=lambda kv: -len(kv[0]))
    ordered = [(re.compile(p), r) for p, r in tables.patterns]
    return ordered + [(re.compile(r"\b" + re.escape(k) + r"\b"), v)
                      for k, v in rules]


def _compile_parts(tables):
    # Seeded from the parts table, then overwritten by words and classes, then
    # filled in by simple columns. That precedence is deliberate: an explicit
    # whole-word entry should win over a component-only one.
    parts = dict(tables.parts)
    for k, v in list(tables.words.items()) + list(tables.classes.items()):
        parts[k.lower()] = v
    for k, v in tables.columns.items():
        if "_" not in k and "." not in k:
            parts.setdefault(k.lower(), v[0].upper() + v[1:])
    return parts


def _assert_idempotent(g, tables):
    """normalize(normalize(x)) must equal normalize(x).

    A rule whose output an earlier rule would have rewritten makes phantom
    detection unreliable, and the symptom -- frozen German reappearing as
    residual noise -- looks like a reviewing problem rather than a config bug.
    """
    probes = set()
    for table in (tables.classes, tables.words, tables.columns, tables.parts):
        probes |= set(table) | set(table.values())
    for probe in sorted(probes):
        once = g.normalize(probe)
        twice = g.normalize(once)
        if once != twice:
            raise GlossaryError(
                f"glossary is not idempotent: {probe!r} -> {once!r} -> {twice!r}")


def build_glossary(tables):
    g = Glossary(_compile_rules(tables), _compile_parts(tables))
    _assert_idempotent(g, tables)
    return g
