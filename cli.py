"""Driver for the rename-review passes.

The passes stay as scripts run in sequence rather than becoming imported
functions. That is deliberate: importing them means restructuring their
module-level bodies, and the replay baseline exists to catch exactly the kind
of drift that churn causes.
"""
import argparse, hashlib, os, pathlib, subprocess, sys

from github import GitHub, GitHubError, resolve_pr
from refs import RefError, fetch, fetch_pull, remote_for

ROOT = pathlib.Path(__file__).resolve().parent
ALL_PASSES = ["pairup.py", "scope.py", "gen2.py", "render2.py"]

# pyproject.toml sits next to cli.py in this repository and is absent from the
# wheel (see its include list), so this is what tells `uv run` inside this
# checkout apart from an install. `uvx --from git+https://...` unpacks the
# wheel into a cache directory that is nobody's working directory and no
# checkout at all -- which is why neither the repository under review nor the
# output directory can be derived from where this file happens to live.
FROM_SOURCE = (ROOT / "pyproject.toml").exists()

# Log names the README and the prototype's muscle memory already use.
LOG_NAME = {"pairup.py": "pair", "scope.py": "scope",
            "gen2.py": "residual", "render2.py": "page"}


def run_passes(passes, env):
    """Run each pass in order, logging full output and echoing the tail.

    Never pipe these into `head`: they die on SIGPIPE mid-write and leave a
    truncated output file, which cost a wrong intermediate answer once already.
    """
    out = pathlib.Path(env["OUT"])
    out.mkdir(parents=True, exist_ok=True)
    for name in passes:
        stem = LOG_NAME.get(name, name.removesuffix(".py"))
        print(f"== {stem}", file=sys.stderr)
        proc = subprocess.run([sys.executable, str(ROOT / name)], env=env,
                              cwd=ROOT, capture_output=True, text=True)
        (out / f"{stem}.log").write_text(proc.stdout)
        if proc.returncode:
            sys.stderr.write(proc.stderr)
            print(f"error: {stem} failed; later passes not run", file=sys.stderr)
            return proc.returncode
        print("\n".join(proc.stdout.splitlines()[-4:]), file=sys.stderr)
    return 0


def repo_root(explicit=None):
    """The checkout to review: --repo, else $REPO, else where the user stands.

    Always a concrete path, never None. The passes run with cwd=ROOT, so their
    own `git rev-parse --show-toplevel` fallback resolves against this tool
    rather than against the repository under review -- this tool's checkout
    under `uv run`, and under `uvx --from git+https://...` a cache directory
    that is no repository at all. Resolving here instead, from the directory
    the user actually invoked the tool in, is what lets a `uvx` run inside the
    target repo work with neither --repo nor $REPO set.

    A subdirectory resolves to the top level, because a pass reads blobs with
    `git show <ref>:<path>`, whose paths are root-relative wherever git runs.
    A path that is no checkout comes back unchanged, so the failure arrives
    from git, naming it, rather than as a silent fallback to somewhere else.
    """
    start = explicit or os.environ.get("REPO") or os.getcwd()
    top = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    return top or str(pathlib.Path(start).resolve())


def out_dir(explicit, repo):
    """Where the build lands: --out, else $OUT, else a default per install.

    `./build` next to the passes only when they are this checkout's own. An
    installed copy lives in a cache directory uv is free to discard, so a
    review written there is one a tool upgrade quietly throws away -- and
    `serve --no-build` would then look for a page that no longer exists. It
    cannot go into the repository under review either: `build/` there is
    Gradle's, and this tool exists for a Java rename. So an installed run
    writes under the user's cache directory, keyed by the checkout so two
    repositories under review do not overwrite each other's page, and every
    pass prints the path it wrote.
    """
    if explicit or os.environ.get("OUT"):
        return explicit or os.environ["OUT"]
    if FROM_SOURCE:
        return str(ROOT / "build")
    cache = (os.environ.get("XDG_CACHE_HOME")
             or pathlib.Path.home() / ".cache")
    key = f"{pathlib.Path(repo).name or 'repo'}-" \
          f"{hashlib.sha256(str(repo).encode()).hexdigest()[:8]}"
    return str(pathlib.Path(cache) / "pr-rename-review" / key)


def _env(args, repo, pull, base, head):
    """The environment every pass reads. Resolved once here so one run asks
    GitHub once and no pass can form a second opinion about which PR this is.

    The PR keys are cleared before being set, so a stray `PR` in the ambient
    environment cannot make an offline build claim to know the pull request.
    """
    env = {**os.environ,
           "REPO": repo, "BASE": base, "HEAD_REF": head,
           "OUT": out_dir(args.out, repo)}
    for key in ("PR", "PR_OWNER", "PR_REPO"):
        env.pop(key, None)
    if pull:
        env |= {"PR": str(pull.number), "PR_OWNER": pull.owner,
                "PR_REPO": pull.repo}
    return env


def fetch_refs(repo, base, head):
    """Update the remotes the overridden refs live on.

    Never fatal: the refs already on disk still describe a real, if older,
    state, and the page names the commits it used. Skipped entirely when
    neither ref tracks a remote -- the replay baseline names commits, and
    there is nothing to fetch for a commit.
    """
    try:
        done, warnings = fetch(repo, [base, head])
    except RefError as exc:
        warnings, done = [f"{exc}; reviewing the refs already on disk"], []
    for remote in done:
        print(f"== fetch {remote}", file=sys.stderr)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


def prepare(args, need_refs=True):
    """Work out what to review. Returns (env, pull); pull is None offline.

    `--base`/`--head` (or $BASE/$HEAD_REF) skip GitHub entirely. That is the
    offline path, and the one tests/conftest.py drives the pinned replay
    baseline through -- which is why it must never consult gh.
    """
    repo = repo_root(args.repo)
    base = args.base or os.environ.get("BASE")
    head = args.head or os.environ.get("HEAD_REF")
    if base and head:
        if need_refs:
            fetch_refs(repo, base, head)
        return _env(args, repo, None, base, head), None
    if base or head:
        raise RefError("--base and --head must be given together, or neither "
                       "-- otherwise name a pull request")

    pull = resolve_pr(args.pr, cwd=repo)
    if not need_refs:
        # serve --no-build: the PR is still needed to sync viewed ticks, but
        # nothing is being built, so nothing is fetched.
        return _env(args, repo, pull, "", ""), pull
    remote, matched = remote_for(repo, pull.owner, pull.repo)
    if not matched:
        # The one scenario where this tool is confidently wrong rather than
        # loudly wrong: in a fork checkout with no upstream remote, origin's
        # own refs/pull/<number>/head can hold an unrelated PR with the same
        # number.
        print(f"warning: no remote points at {pull.owner}/{pull.repo}; "
              f"falling back to {remote}, whose refs/pull/{pull.number}/head "
              "may name a different pull request", file=sys.stderr)
    print(f"== fetch {remote} refs/pull/{pull.number}/head", file=sys.stderr)
    base, head, warnings = fetch_pull(repo, remote, pull.number, pull.base_ref)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return _env(args, repo, pull, base, head), pull


class _OfflineGitHub:
    """Stands in when gh is unavailable, so the page still loads and honestly
    reports that nothing is being written back."""

    def __init__(self, reason):
        self.reason = reason

    def viewed_states(self):
        raise GitHubError(self.reason)

    def set_viewed(self, path, viewed):
        raise GitHubError(self.reason)


def _github(pull, cwd=None):
    """The user's own gh login, or an offline stand-in with the reason.

    `gh` resolves the repository from its working directory, so every call is
    made inside the checkout under review rather than inside this tool.
    """
    if pull is None:
        return _OfflineGitHub("--base/--head given, so no pull request is "
                              "known; name one to sync viewed state")
    return GitHub(pull.owner, pull.repo, pull.number, cwd=cwd)


# Real defaults for the flags shared between `p` and every subparser. Kept
# out of add_argument()'s own `default=` -- see the SUPPRESS comment in
# _parser() for why -- and applied once after parsing instead.
_COMMON_DEFAULTS = {"repo": None, "base": None, "head": None, "out": None,
                    "no_build": False, "no_browser": False}


def _parser():
    # A parent parser rather than flags on `p` alone: with only the latter,
    # argparse accepts a flag before the subcommand but not after, and the
    # README shows `pr-rename-review serve 259 --no-browser` -- flags-after
    # has to parse too. `parents=[common]` on each subparser makes the
    # tokens parse either way, but it is not enough by itself: when the
    # subparsers action dispatches, it parses the remainder with a *fresh*
    # namespace and then copies every one of that namespace's keys onto the
    # real one -- including the untouched flags, filled in with their
    # defaults. That unconditionally stomps a value a flag set *before* the
    # subcommand. Giving each common action `default=SUPPRESS` stops it: an
    # unset flag is then simply absent from the fresh namespace rather than
    # present with a default, so the copy has nothing to stomp with. The
    # real defaults go on afterward, in main(), once both passes are done.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=argparse.SUPPRESS,
                        help="checkout to diff (default: $REPO, else the "
                            "checkout you are standing in, so running this "
                            "from the target repo needs neither)")
    common.add_argument("--base", default=argparse.SUPPRESS,
                        help="base ref, skipping GitHub (needs --head)")
    common.add_argument("--head", default=argparse.SUPPRESS,
                        help="head ref, skipping GitHub (needs --base)")
    common.add_argument("--out", default=argparse.SUPPRESS,
                        help="output directory (default: this tool's own "
                            "build/ when run from its checkout, otherwise "
                            "~/.cache/pr-rename-review/<checkout>)")
    common.add_argument("--no-build", action="store_true",
                        default=argparse.SUPPRESS,
                        help="serve the existing output without rebuilding")
    common.add_argument("--no-browser", action="store_true",
                        default=argparse.SUPPRESS,
                        help="do not open a browser when serving")

    p = argparse.ArgumentParser(
        prog="pr-rename-review", parents=[common],
        description="Review a rename-heavy PR that GitHub's diff cannot pair")
    sub = p.add_subparsers(dest="cmd")
    for name, help_text in (
            ("build", "run the passes and write the page"),
            ("pairs", "print the pairing disagreement report"),
            ("serve", "build, then serve the page on localhost")):
        s = sub.add_parser(name, help=help_text, parents=[common])
        s.add_argument("pr", nargs="?", metavar="PR",
                       help="pull request: number, #number or URL "
                            "(default: the PR of the checked-out branch)")
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    args = parser.parse_args(argv)
    for dest, default in _COMMON_DEFAULTS.items():
        if not hasattr(args, dest):
            setattr(args, dest, default)

    if not args.cmd:
        parser.print_usage(sys.stderr)
        print("error: pick a subcommand: build, pairs, serve", file=sys.stderr)
        return 2

    building = args.cmd != "serve" or not args.no_build
    try:
        env, pull = prepare(args, need_refs=building)
    except (GitHubError, RefError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.cmd in ("pairs", "build"):
        return run_passes(["pairup.py"] if args.cmd == "pairs" else ALL_PASSES,
                          env)

    # serve. Rebuilds every time unless told not to: the passes take seconds,
    # and a staleness heuristic that guesses wrong serves a stale page that
    # looks current -- the exact failure this tool exists to prevent.
    from server import serve
    if building:
        code = run_passes(ALL_PASSES, env)
        if code:
            return code
    page = pathlib.Path(env["OUT"]) / "hidden-renames.html"
    if not page.exists():
        print(f"error: {page} does not exist; run without --no-build",
              file=sys.stderr)
        return 1
    serve(page, _github(pull, cwd=env["REPO"] or None),
          open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
