import json
import sys
from collections.abc import Mapping


def write_result(data: Mapping[str, object], status: str = "ok", *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    # pythonw has no standard streams; execution history remains in SQLite.
    if stream is None:
        return
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")
    print(
        json.dumps({"status": status, **data}, ensure_ascii=False, default=str),
        file=stream,
    )
