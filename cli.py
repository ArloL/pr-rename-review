"""Driver for the rename-review passes.

The passes stay as scripts run in sequence rather than becoming imported
functions. That is deliberate: importing them means restructuring their
module-level bodies, and the replay baseline exists to catch exactly the kind
of drift that churn causes.
"""
import argparse, os, pathlib, subprocess, sys

from github import GitHub, GitHubError, resolve_repo, resolve_target

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


def _env(args):
    from config import load_config
    cfg = load_config(ROOT / ".pr-rename-review.toml")
    return {**os.environ,
            "REPO": args.repo or os.environ.get("REPO", ""),
            "BASE": args.base or os.environ.get("BASE") or cfg.base,
            "HEAD_REF": args.head or os.environ.get("HEAD_REF") or cfg.head,
            "OUT": args.out or os.environ.get("OUT") or str(ROOT / "build")}


def fetch_refs(env):
    """Fetch before building, so `build` alone shows the PR as it stands.

    Skipped entirely when neither ref tracks a remote -- the replay baseline
    names commits, and there is nothing to fetch for a commit.
    """
    from refs import RefError, fetch
    repo = env["REPO"] or None
    try:
        done, warnings = fetch(repo, [env["BASE"], env["HEAD_REF"]])
    except RefError as exc:
        warnings, done = [f"{exc}; reviewing the refs already on disk"], []
    for remote in done:
        print(f"== fetch {remote}", file=sys.stderr)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


class _OfflineGitHub:
    """Stands in when gh is unavailable, so the page still loads and honestly
    reports that nothing is being written back."""

    def __init__(self, reason):
        self.reason = reason

    def viewed_states(self):
        raise GitHubError(self.reason)

    def set_viewed(self, path, viewed):
        raise GitHubError(self.reason)


def _github(cfg, cwd=None):
    """The user's own gh login, or an offline stand-in with the reason.

    `gh` resolves the repository from its working directory, so every call is
    made inside the checkout under review rather than inside this tool.
    """
    try:
        if cfg.pr:
            owner, repo = resolve_repo(cwd=cwd)
            pr = cfg.pr
        else:
            owner, repo, pr = resolve_target(cwd=cwd)
        return GitHub(owner, repo, pr, cwd=cwd)
    except (GitHubError, KeyError) as exc:
        print(f"warning: GitHub sync unavailable ({exc}); viewed state will "
              "be local to your browser", file=sys.stderr)
        return _OfflineGitHub(str(exc))


def _parser():
    p = argparse.ArgumentParser(
        prog="pr-rename-review",
        description="Review a rename-heavy PR that GitHub's diff cannot pair")
    p.add_argument("--repo", help="checkout to diff (default: $REPO or cwd)")
    p.add_argument("--base", help="base ref (default: config [repo].base)")
    p.add_argument("--head", help="head ref (default: config [repo].head)")
    p.add_argument("--out", help="output directory (default: ./build)")
    p.add_argument("--no-build", action="store_true",
                   help="serve the existing build/ without rebuilding")
    p.add_argument("--no-browser", action="store_true",
                   help="do not open a browser when serving")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("build", help="run the passes and write the page")
    sub.add_parser("pairs", help="print the pairing disagreement report")
    sub.add_parser("serve", help="build, then serve the page on localhost")
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    args = parser.parse_args(argv)

    if not args.cmd:
        parser.print_usage(sys.stderr)
        print("error: pick a subcommand: build, pairs, serve", file=sys.stderr)
        return 2
    env = _env(args)
    if args.cmd in ("pairs", "build"):
        fetch_refs(env)
        return run_passes(["pairup.py"] if args.cmd == "pairs" else ALL_PASSES,
                          env)

    # serve. Rebuilds every time unless told not to: the passes take seconds,
    # and a staleness heuristic that guesses wrong serves a stale page that
    # looks current -- the exact failure this tool exists to prevent.
    from config import load_config
    from server import serve
    if not args.no_build:
        fetch_refs(env)
        code = run_passes(ALL_PASSES, env)
        if code:
            return code
    page = pathlib.Path(env["OUT"]) / "hidden-renames.html"
    if not page.exists():
        print(f"error: {page} does not exist; run without --no-build",
              file=sys.stderr)
        return 1
    cfg = load_config(ROOT / ".pr-rename-review.toml")
    serve(page, _github(cfg, cwd=env["REPO"] or None),
          open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
