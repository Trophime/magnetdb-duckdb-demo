"""Write a starting group_order.json from a real record's actual group names.

Unlike style.json, there's no in-code canonical list of sensor-group names to
seed a default from — group vocabulary only exists once real data files are
parsed. This script loads one or more real source files via
magnetdb_analysis.get_overview_group_entries() and writes the group names it
discovers, in their current order, as a starting point to hand-edit into the
desired display order. See PLAN_group_order.md for the resolution order this
file participates in (~/.config/magnetdb/group_order.json > the bundled
group_order.json > no reordering).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from magnetdb_analysis import get_overview_group_entries

_DEFAULT_OUTPUT = Path.home() / ".config" / "magnetdb" / "group_order.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", "-i", action="append", required=True, dest="files",
        metavar="FILENAME", help="source data filename (repeatable)",
    )
    parser.add_argument(
        "--housing", required=True, help="housing identifier",
    )
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

    group_entries = get_overview_group_entries(args.files, args.housing)
    if not group_entries:
        print("error: no data groups found for the given files/housing", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(list(group_entries.keys()), f, indent=2)
        f.write("\n")
    print(f"wrote {len(group_entries)} group name(s) to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
