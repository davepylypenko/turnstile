import argparse, sys
from . import __version__

def build_parser():
    p = argparse.ArgumentParser(prog="turnstile", description="Evidence-gated delivery. No ticket, no entry.")
    p.add_argument("--version", action="version", version="turnstile " + __version__)
    p.add_argument("--delivery", help="path to the delivery dir (default: resolved from .turnstile)")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("status", help="reconcile + where we are")
    return p, sub

def main(argv=None):
    parser, _ = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
