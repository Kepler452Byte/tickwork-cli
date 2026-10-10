import codecs
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import IO, Any

from tickwork_cli.app.task.repository.task_run_repository import LOG_LIMIT, TaskRunRepository
from tickwork_cli.app.task.schema.task_schema import Task
from tickwork_cli.common.windows_job import WindowsJob


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        # /T kills descendants too; never interpolate user argv in a shell.
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15
        )
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_task(task: Task, repository: TaskRunRepository) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    repository.start(run_id, task.id, os.getpid())
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    job: WindowsJob | None = None
    code: int | None = None
    status = "failed"
    truncated = False
    total = 0
    chunks: queue.Queue[tuple[str, bytes | None]] = queue.Queue(maxsize=32)

    def read(stream: str, pipe: IO[bytes]) -> None:
        try:
            while data := pipe.read1(8192):  # type: ignore[attr-defined]
                chunks.put((stream, data))
        finally:
            pipe.close()
            chunks.put((stream, None))

    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            task.argv,
            cwd=task.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
        if sys.platform == "win32":
            job = WindowsJob(process.pid)
        assert process.stdout is not None and process.stderr is not None
        for stream, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            threading.Thread(target=read, args=(stream, pipe), daemon=True).start()
        decoders = {
            stream: codecs.getincrementaldecoder("utf-8")("replace")
            for stream in ("stdout", "stderr")
        }
        completed = 0
        timed_out = False
        while completed < 2:
            if time.monotonic() - started >= task.timeout and not timed_out:
                timed_out = True
                if job:
                    job.terminate()
                else:
                    stop_process(process)
            try:
                stream, data = chunks.get(timeout=0.1)
            except queue.Empty:
                continue
            if data is None:
                completed += 1
                text = decoders[stream].decode(b"", final=True)
            else:
                remaining = max(0, LOG_LIMIT - total)
                accepted = data[:remaining]
                total += len(accepted)
                truncated |= len(accepted) != len(data)
                text = decoders[stream].decode(accepted)
            if text:
                repository.append(run_id, stream, text)
        code = process.wait(timeout=15)
        status = "timeout" if timed_out else "succeeded" if code == 0 else "failed"
    except OSError as exc:
        repository.append(run_id, "stderr", str(exc))
    except BaseException:
        if process:
            if job:
                job.terminate()
            else:
                stop_process(process)
        repository.finish(
            run_id,
            "interrupted",
            process.poll() if process else None,
            time.monotonic() - started,
            truncated,
        )
        raise
    finally:
        if job:
            job.close()
    repository.finish(run_id, status, code, time.monotonic() - started, truncated)
    result = repository.result(run_id)
    result["success_criterion"] = (
        "Process exit code only; inspect logs and expected artifacts separately."
    )
    return result
