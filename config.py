"""Load `.pr-rename-review.toml`.

Data only: which refs to review and which PR to sync ticks with. Pairing
needs no vocabulary -- the branch's own rename commits record the moves.
"""
import pathlib
import tomllib
from dataclasses import dataclass

DEFAULT_NAME = ".pr-rename-review.toml"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    base: str
    head: str
    pr: int | None


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

    return Config(base=repo["base"], head=repo["head"], pr=repo.get("pr"))
