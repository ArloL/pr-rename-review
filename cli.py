"""Driver for the rename-review passes.

The passes stay as scripts run in sequence rather than becoming imported
functions. That is deliberate: importing them means restructuring their
module-level bodies, and the replay baseline exists to catch exactly the kind
of drift that churn causes.
"""
import argparse, os, pathlib, subprocess, sys

from github import GitHub, GitHubError, resolve_pr
from refs import RefError, fetch, fetch_pull, remote_for

ROOT = pathlib.Path(__file__).resolve().parent
ALL_PASSES = ["pairup.py", "scope.py", "gen2.py", "render2.py"]

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


def _env(args, pull, base, head):
    """The environment every pass reads. Resolved once here so one run asks
    GitHub once and no pass can form a second opinion about which PR this is.

    The PR keys are cleared before being set, so a stray `PR` in the ambient
    environment cannot make an offline build claim to know the pull request.
    """
    env = {**os.environ,
           "REPO": args.repo or os.environ.get("REPO", ""),
           "BASE": base, "HEAD_REF": head,
           "OUT": args.out or os.environ.get("OUT") or str(ROOT / "build")}
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
    repo = args.repo or os.environ.get("REPO") or None
    base = args.base or os.environ.get("BASE")
    head = args.head or os.environ.get("HEAD_REF")
    if base and head:
        if need_refs:
            fetch_refs(repo, base, head)
        return _env(args, None, base, head), None
    if base or head:
        raise RefError("--base and --head must be given together, or neither "
                       "-- otherwise name a pull request")

    pull = resolve_pr(args.pr, cwd=repo)
    if not need_refs:
        # serve --no-build: the PR is still needed to sync viewed ticks, but
        # nothing is being built, so nothing is fetched.
        return _env(args, pull, "", ""), pull
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
    return _env(args, pull, base, head), pull


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
                        help="checkout to diff (default: $REPO; falls back "
                            "to cwd, which is this tool's own directory "
                            "when run via `uv run`, not the checkout you "
                            "mean)")
    common.add_argument("--base", default=argparse.SUPPRESS,
                        help="base ref, skipping GitHub (needs --head)")
    common.add_argument("--head", default=argparse.SUPPRESS,
                        help="head ref, skipping GitHub (needs --base)")
    common.add_argument("--out", default=argparse.SUPPRESS,
                        help="output directory (default: ./build)")
    common.add_argument("--no-build", action="store_true",
                        default=argparse.SUPPRESS,
                        help="serve the existing build/ without rebuilding")
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
