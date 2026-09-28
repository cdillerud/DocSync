from pathlib import Path
import re


ROOT = Path("bc-extension/document-delivery/src")
PATTERN = re.compile(
    r"^\s*(table|page|codeunit|pageextension|tableextension|enum|permissionset)\s+(\d+)\s+",
    re.IGNORECASE,
)


def main() -> None:
    seen = {}
    errors = []

    for path in sorted(ROOT.rglob("*.al")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = PATTERN.match(line)
            if not match:
                continue

            object_type = match.group(1).lower()
            object_id = int(match.group(2))
            key = (object_type, object_id)

            if not 70150000 <= object_id <= 70150099:
                errors.append(
                    f"{path}: {object_type} {object_id} is outside 70150000..70150099"
                )

            if key in seen:
                errors.append(
                    f"Duplicate {object_type} {object_id}: {seen[key]} and {path}"
                )

            seen[key] = path
            break

    if errors:
        raise SystemExit("\n".join(errors))

    print(f"Validated {len(seen)} AL object identifiers")


if __name__ == "__main__":
    main()
