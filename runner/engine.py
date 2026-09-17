from __future__ import annotations

import io
import json
import posixpath
import secrets
import tarfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.utils.socket import STDERR, STDOUT, frames_iter

from runner.models import ARTIFACT_LIMIT, ExecuteRequest, Limits, ScriptRequest, validate_wire_value
from runner.wrappers import Bundle, build_execute_bundle, build_script_bundle, parse_control_frame


@dataclass
class OutputCollector:
    limit: int
    stdout_parts: list[bytes] = field(default_factory=list)
    stderr_parts: list[bytes] = field(default_factory=list)
    size: int = 0
    exceeded: bool = False

    def add(self, stream: Literal["stdout", "stderr"], chunk: bytes) -> bool:
        if self.exceeded:
            return False
        remaining = max(0, self.limit - self.size)
        keep = min(len(chunk), remaining)
        if keep:
            getattr(self, f"{stream}_parts").append(chunk[:keep])
            self.size += keep
        if keep < len(chunk):
            self.exceeded = True
            return False
        return True

    @property
    def stdout(self) -> bytes:
        return b"".join(self.stdout_parts)

    @property
    def stderr(self) -> bytes:
        return b"".join(self.stderr_parts)


def build_archive(files: dict[str, bytes], *, max_bytes: int) -> bytes:
    total = sum(len(value) for value in files.values())
    if total > max_bytes:
        raise ValueError("archive payload exceeds limit")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(files):
            normalized = posixpath.normpath(name)
            if normalized.startswith("../") or normalized.startswith("/") or normalized in {".", ".."}:
                raise ValueError("unsafe archive path")
            payload = files[name]
            info = tarfile.TarInfo(normalized)
            info.size = len(payload)
            info.mode = 0o600
            info.uid = info.gid = 10001
            info.uname = info.gname = "runner"
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


def classify_exit(*, trigger: str | None, oom_killed: bool, exit_code: int, has_control: bool) -> str:
    if trigger == "output":
        return "output_limit"
    if trigger == "timeout":
        return "time_limit"
    if oom_killed:
        return "memory_limit"
    if exit_code != 0:
        return "runtime_error"
    if not has_control:
        return "system_error"
    return "ok"


def container_options(*, memory_mb: int, pids: int, read_only: bool) -> dict:
    options = {
        "detach": True,
        "stdin_open": True,
        "network_disabled": True,
        "user": "10001:10001",
        "working_dir": "/job",
        "mem_limit": f"{memory_mb}m",
        "memswap_limit": f"{memory_mb}m",
        "nano_cpus": 1_000_000_000,
        "pids_limit": pids,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "labels": {"com.loopcode.sandbox": "true"},
        "read_only": read_only,
    }
    if read_only:
        options["tmpfs"] = {"/tmp": "rw,noexec,nosuid,nodev,size=64m,mode=1777"}
    return options


class DockerUnavailable(RuntimeError):
    pass


@dataclass
class MonitoredRun:
    status: str
    stdout: bytes
    stderr: bytes
    exit_code: int
    oom_killed: bool
    elapsed_ms: float


class DockerRunner:
    """Runs untrusted source only through restricted Docker containers."""

    def __init__(self, client=None) -> None:
        self._client = client

    def _docker(self):
        try:
            if self._client is None:
                self._client = docker.from_env(timeout=10)
            return self._client
        except DockerException as exc:
            raise DockerUnavailable("Docker is unavailable") from exc

    def health(self) -> dict:
        try:
            self._docker().ping()
        except (DockerException, DockerUnavailable) as exc:
            return {"status": "unavailable", "docker_available": False, "detail": "Docker 연결을 확인하세요."}
        return {"status": "ok", "docker_available": True, "detail": "Docker를 사용할 수 있습니다."}

    def execute(self, request: ExecuteRequest) -> dict:
        bundle = build_execute_bundle(request)
        client = self._docker()
        image = None
        try:
            image, compile_run = self._prepare_image(bundle, request.limits)
            if image is None:
                result = self._failure_result(compile_run)
                return {"results": [{**result, "id": case.id} for case in request.cases]}
            results = []
            pids = 128 if request.language == "java" else 64
            for case in request.cases:
                outcome = self._run_case(image.id, bundle.runtime_command, {"args": case.args}, request.limits, pids)
                item = self._outcome_result(outcome, request.signature.return_type)
                item["id"] = case.id
                results.append(item)
            return {"results": results}
        except DockerException as exc:
            raise DockerUnavailable("Docker transport failed") from exc
        finally:
            if image is not None:
                try:
                    client.images.remove(image.id, force=True)
                except NotFound:
                    pass
                except DockerException as exc:
                    raise DockerUnavailable("temporary image cleanup failed") from exc

    def script(self, request: ScriptRequest) -> dict:
        bundle = build_script_bundle(request)
        client = self._docker()
        image = None
        try:
            image, compile_run = self._prepare_image(bundle, request.limits)
            if image is None:
                return self._failure_result(compile_run)
            outcome = self._run_case(image.id, bundle.runtime_command, {"payload": request.payload}, request.limits, 64)
            return self._outcome_result(outcome, None)
        except DockerException as exc:
            raise DockerUnavailable("Docker transport failed") from exc
        finally:
            if image is not None:
                try:
                    client.images.remove(image.id, force=True)
                except NotFound:
                    pass
                except DockerException as exc:
                    raise DockerUnavailable("temporary image cleanup failed") from exc

    def _prepare_image(self, bundle: Bundle, limits: Limits):
        client = self._docker()
        container = None
        try:
            options = container_options(memory_mb=1024, pids=128, read_only=False)
            container = client.containers.create(bundle.image, command=bundle.compile_command, **options)
            archive = build_archive(bundle.files, max_bytes=ARTIFACT_LIMIT)
            if not container.put_archive("/job", archive):
                raise DockerUnavailable("Docker rejected source archive")
            run = self._monitor(container, timeout_seconds=30.0, output_limit=limits.output_kb * 1024, stdin=None)
            if run.status != "ok" or run.exit_code != 0:
                if run.status in {"ok", "runtime_error"}:
                    run.status = "compile_error"
                return None, run
            stream, _ = container.get_archive("/job")
            size = 0
            for chunk in stream:
                size += len(chunk)
                if size > ARTIFACT_LIMIT:
                    run.status = "system_error"
                    run.stderr += b"compiled artifact exceeds 32MiB"
                    return None, run
            repository = f"loopcode-job-{uuid.uuid4().hex}"
            image = container.commit(repository=repository, tag="latest")
            return image, run
        finally:
            if container is not None:
                self._remove_container(container)

    def _run_case(self, image: str, command: list[str], message: dict, limits: Limits, pids: int) -> tuple[MonitoredRun, str]:
        container = None
        token = secrets.token_hex(24)
        payload = json.dumps({"token": token, **message}, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        try:
            options = container_options(memory_mb=limits.memory_mb, pids=pids, read_only=True)
            container = self._docker().containers.create(image, command=command, **options)
            outcome = self._monitor(container, timeout_seconds=limits.time_ms / 1000, output_limit=limits.output_kb * 1024, stdin=payload)
            return outcome, token
        finally:
            if container is not None:
                self._remove_container(container)

    def _monitor(self, container, *, timeout_seconds: float, output_limit: int, stdin: bytes | None) -> MonitoredRun:
        collector = OutputCollector(output_limit)
        trigger: list[str | None] = [None]
        reader_error: list[Exception] = []
        wait_result: list[dict] = []
        wait_error: list[Exception] = []
        finished = threading.Event()
        params = {"stdout": 1, "stderr": 1, "stream": 1, "stdin": 1 if stdin is not None else 0}
        attached = container.attach_socket(params=params)

        def reader() -> None:
            try:
                for stream_id, data in frames_iter(attached, tty=False):
                    stream = "stdout" if stream_id == STDOUT else "stderr" if stream_id == STDERR else None
                    if stream is None:
                        continue
                    if not collector.add(stream, data):
                        if trigger[0] is None:
                            trigger[0] = "output"
                        self._kill(container)
                        return
            except Exception as exc:  # transport errors are surfaced after cleanup
                reader_error.append(exc)

        def waiter() -> None:
            try:
                wait_result.append(container.wait(timeout=max(40.0, timeout_seconds + 10.0)))
            except Exception as exc:
                wait_error.append(exc)
            finally:
                finished.set()

        started = time.monotonic()
        thread = threading.Thread(target=reader, name=f"runner-output-{container.id[:8]}", daemon=True)
        wait_thread = threading.Thread(target=waiter, name=f"runner-wait-{container.id[:8]}", daemon=True)
        try:
            container.start()
            thread.start()
            wait_thread.start()
            if stdin is not None:
                raw = getattr(attached, "_sock", attached)
                raw.sendall(stdin)
            if not finished.wait(timeout_seconds):
                if trigger[0] is None:
                    trigger[0] = "timeout"
                self._kill(container)
                finished.wait(5)
            wait_thread.join(timeout=1)
            thread.join(timeout=5)
            if wait_error:
                raise DockerUnavailable("Docker wait transport failed") from wait_error[0]
            if not wait_result:
                raise DockerUnavailable("Docker did not report container exit")
            container.reload()
            state = container.attrs.get("State", {})
            exit_code = int(wait_result[0].get("StatusCode", state.get("ExitCode", 1)))
            oom = bool(state.get("OOMKilled", False))
            elapsed = (time.monotonic() - started) * 1000
            status = classify_exit(trigger=trigger[0], oom_killed=oom, exit_code=exit_code, has_control=True)
            if reader_error and trigger[0] is None:
                raise DockerUnavailable("Docker output transport failed") from reader_error[0]
            return MonitoredRun(status, collector.stdout, collector.stderr, exit_code, oom, elapsed)
        finally:
            try:
                attached.close()
            except Exception:
                pass

    def _outcome_result(self, value: tuple[MonitoredRun, str], descriptor) -> dict:
        outcome, token = value
        control, stdout, stderr = parse_control_frame(outcome.stdout, outcome.stderr, token)
        status = classify_exit(
            trigger="output" if outcome.status == "output_limit" else "timeout" if outcome.status == "time_limit" else None,
            oom_killed=outcome.oom_killed,
            exit_code=outcome.exit_code,
            has_control=control is not None,
        )
        result_value = None
        time_ms = outcome.elapsed_ms
        memory_kb = 0
        if status == "ok" and control is not None:
            result_value = control.get("value")
            try:
                time_ms = max(0.0, float(control["time_ms"]))
                memory_kb = max(0, int(control["memory_kb"]))
                if descriptor is not None:
                    validate_wire_value(result_value, descriptor)
                else:
                    json.dumps(result_value, ensure_ascii=False, allow_nan=False)
            except (KeyError, TypeError, ValueError):
                status = "runtime_error"
                result_value = None
        return {
            "status": status,
            "value": result_value,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "time_ms": round(time_ms, 3),
            "memory_kb": memory_kb,
        }

    @staticmethod
    def _failure_result(outcome: MonitoredRun) -> dict:
        status = outcome.status if outcome.status != "ok" else "compile_error"
        return {
            "status": status,
            "value": None,
            "stdout": outcome.stdout.decode("utf-8", errors="replace"),
            "stderr": outcome.stderr.decode("utf-8", errors="replace"),
            "time_ms": round(outcome.elapsed_ms, 3),
            "memory_kb": 0,
        }

    @staticmethod
    def _kill(container) -> None:
        try:
            container.kill()
        except (APIError, NotFound):
            pass

    @staticmethod
    def _remove_container(container) -> None:
        try:
            container.remove(force=True)
        except NotFound:
            pass
        except DockerException as exc:
            raise DockerUnavailable("sandbox cleanup failed") from exc
