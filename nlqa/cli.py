import argparse


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="nlqa",
        description="Run plain-English QA test cases in a browser with evidence-based results.",
    )
    parser.add_argument("--version", action="version", version="nl-test-runner 0.1.0")
    parser.add_subparsers(dest="command")
    return parser


def main() -> int:
    """Run the command-line interface."""
    build_parser().parse_args()
    return 0
