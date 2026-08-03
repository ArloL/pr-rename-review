"""Load `.pr-rename-review.toml`.

Data only. All pairing logic lives in pairup.py, because vocabulary belongs
in config and behaviour does not.
"""
import pathlib
import tomllib
from dataclasses import dataclass, field

DEFAULT_NAME = ".pr-rename-review.toml"


class ConfigError(Exception):
    pass


@dataclass
class Pairing:
    path_rules: list[tuple[str, str]] = field(default_factory=list)
    basenames: dict[str, str] = field(default_factory=dict)
    words: list[tuple[str, str]] = field(default_factory=list)
    dir_scope: str | None = None
    dir_segments: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    base: str
    head: str
    pr: int | None
    pairing: Pairing


def _pairs(rows, where):
    """Read a list of [from, to] rows, preserving file order. Order matters
    for pairing.words: it is applied as a sequence rather than sorted."""
    out = []
    for row in rows:
        if not (isinstance(row, list) and len(row) == 2):
            raise ConfigError(f"{where}: expected [from, to] pairs, got {row!r}")
        out.append((row[0], row[1]))
    return out


def load_config(path=None):
    path = pathlib.Path(path) if path else pathlib.Path.cwd() / DEFAULT_NAME
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    with open(path, "rb") as fh:
        try:
            raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc

    repo = raw.get("repo")
    if not repo or "base" not in repo or "head" not in repo:
        raise ConfigError(f"{path}: [repo] must set both base and head")

    p = raw.get("pairing", {})
    dirs = p.get("dir_segments", {})
    pairing = Pairing(
        path_rules=_pairs(p.get("path_rules", []), "pairing.path_rules"),
        basenames=dict(p.get("basenames", {})),
        words=_pairs(p.get("words", []), "pairing.words"),
        dir_scope=dirs.get("scope"),
        dir_segments=dict(dirs.get("segments", {})),
    )

    return Config(base=repo["base"], head=repo["head"], pr=repo.get("pr"),
                  pairing=pairing)
