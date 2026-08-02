"""Driver for the rename-review passes.

The passes stay as scripts run in sequence rather than becoming imported
functions. That is deliberate: importing them means restructuring their
module-level bodies, and the replay baseline exists to catch exactly the kind
of drift that churn causes.
"""
import argparse, os, pathlib, subprocess, sys

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


def _parser():
    p = argparse.ArgumentParser(
        prog="pr-rename-review",
        description="Review a rename-heavy PR that GitHub's diff cannot pair")
    p.add_argument("--repo", help="checkout to diff (default: $REPO or cwd)")
    p.add_argument("--base", help="base ref (default: config [repo].base)")
    p.add_argument("--head", help="head ref (default: config [repo].head)")
    p.add_argument("--out", help="output directory (default: ./build)")
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
    if args.cmd == "pairs":
        return run_passes(["pairup.py"], _env(args))
    if args.cmd == "build":
        return run_passes(ALL_PASSES, _env(args))
    print("error: `serve` is not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
