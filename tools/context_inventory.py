"""Read-only, date-explicit inventory of expired evidence in an immutable Git ref."""

import argparse
import json
import subprocess
from datetime import date


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    args = parser.parse_args()

    def read(path):
        return subprocess.check_output(
            ["git", "show", f"{args.ref}:{path}"], text=True, encoding="utf-8"
        )

    taxonomy = json.loads(read("project-context/taxonomy.yaml"))
    limit = taxonomy["freshness"]["current_max_age_days"]
    entries = []
    for kind in ("sources", "records"):
        for item in map(json.loads, read(f"project-context/{kind}.jsonl").splitlines()):
            age = (args.as_of - date.fromisoformat(item["last_verified_at"])).days
            if item["freshness"] == "current" and age > limit:
                entries.append({"type": kind, "original": item, "age_days": age})
    print(json.dumps({"as_of": args.as_of.isoformat(), "entries": entries}, indent=2))


if __name__ == "__main__":
    main()
