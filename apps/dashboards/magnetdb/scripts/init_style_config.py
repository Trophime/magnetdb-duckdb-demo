"""Write a default style.json for the dashboard's per-file-type trace styling.

Writes today's FileTypeStyles() in-code defaults to a JSON file — a starting
point to edit into a custom override. See PLOT_STYLE.md for the resolution
order this file participates in ($MAGNETDB_FILE_TYPE_STYLES env var >
~/.config/magnetdb/style.json > the bundled style.json > in-code defaults).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from magnetdb_plot import FileTypeStyles, save_file_type_styles

_DEFAULT_OUTPUT = Path.home() / ".config" / "magnetdb" / "style.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", "-o", default=str(_DEFAULT_OUTPUT), metavar="FILE",
        help=f"output path (default: {_DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--force", "-f", action="store_true", help="overwrite an existing file",
    )
    args = parser.parse_args()

    out = Path(args.output)
    if out.exists() and not args.force:
        print(f"error: {out} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    save_file_type_styles(FileTypeStyles(), out)
    print(f"wrote default style config to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
