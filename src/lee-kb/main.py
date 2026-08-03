"""Bootstrap command-line entry point for Lee Knowledge Base."""

import argparse

from . import __version__


def main() -> None:
    """Show the bootstrap CLI until the retrieval commands are implemented."""
    parser = argparse.ArgumentParser(
        prog="lee-kb",
        description=(
            "Lee Knowledge Base — a governed knowledge fabric for "
            "permission-aware federated retrieval."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.epilog = (
        "The ingestion and retrieval pipeline is under active development. "
        "See README.md and sprint-plan.md for the current scope."
    )
    parser.parse_args()
    parser.print_help()


if __name__ == "__main__":
    main()
