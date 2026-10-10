import json
from collections.abc import Mapping


def write_result(data: Mapping[str, object], status: str = "ok") -> None:
    print(json.dumps({"status": status, **data}, ensure_ascii=False, indent=2, default=str))
