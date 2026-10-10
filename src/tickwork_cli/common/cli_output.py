import json
import sys
from collections.abc import Mapping


def write_result(data: Mapping[str, object], status: str = "ok", *, error: bool = False) -> None:
    print(
        json.dumps({"status": status, **data}, ensure_ascii=False, default=str),
        file=sys.stderr if error else sys.stdout,
    )
