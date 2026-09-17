from __future__ import annotations

import io
import json
import posixpath
import secrets
import socket
import tarfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.utils.socket import STDERR, STDOUT, frames_iter

from runner.models import ARTIFACT_LIMIT, REQUEST_LIMIT, ExecuteRequest, Limits, ScriptRequest, validate_wire_value
from runner.wrappers import CONTROL_PREFIX, Bundle, build_execute_bundle, build_script_bundle


CONTROL_LIMIT = REQUEST_LIMIT + 64 * 1024


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


class RuntimeOutputCollector:
    """Separates the private result frame from bounded user output as bytes arrive."""

    def __init__(self, *, user_limit: int, control_limit: int, token: str) -> None:
        self._user = OutputCollector(user_limit)
        self._marker = ("\n" + CONTROL_PREFIX + token + ":").encode()
        self._pending = bytearray()
        self._control = bytearray()
        self._control_limit = control_limit
        self._in_control = False
        self._control_complete = False
        self._control_exceeded = False

    def add(self, stream: Literal["stdout", "stderr"], chunk: bytes) -> bool:
        if self.exceeded:
            return False
        if stream == "stdout":
            return self._user.add(stream, chunk)
        return self._add_stderr(chunk)

    def _add_stderr(self, chunk: bytes) -> bool:
        if self._control_complete:
            return self._user.add("stderr", chunk)
        if self._in_control:
            return self._add_control(chunk)

        data = bytes(self._pending) + chunk
        self._pending.clear()
        marker_index = data.find(self._marker)
        if marker_index >= 0:
            if not self._user.add("stderr", data[:marker_index]):
                return False
            self._in_control = True
            return self._add_control(data[marker_index + len(self._marker) :])

        suffix_size = self._marker_prefix_suffix_size(data)
        confirmed = data[:-suffix_size] if suffix_size else data
        if suffix_size:
            self._pending.extend(data[-suffix_size:])
        return self._user.add("stderr", confirmed)

    def _add_control(self, data: bytes) -> bool:
        end = data.find(b"\n")
        control_data = data if end < 0 else data[:end]
        remaining = max(0, self._control_limit - len(self._control))
        self._control.extend(control_data[:remaining])
        if len(control_data) > remaining:
            self._control_exceeded = True
            return False
        if end >= 0:
            self._control_complete = True
            self._in_control = False
            return self._user.add("stderr", data[end + 1 :])
        return True

    def _marker_prefix_suffix_size(self, data: bytes) -> int:
        maximum = min(len(data), len(self._marker) - 1)
        for size in range(maximum, 0, -1):
            if data.endswith(self._marker[:size]):
                return size
        return 0

    def finish(self) -> bool:
        if not self._in_control and not self._control_complete and self._pending:
            pending = bytes(self._pending)
            self._pending.clear()
            return self._user.add("stderr", pending)
        return not self.exceeded

    @property
    def exceeded(self) -> bool:
        return self._user.exceeded or self._control_exceeded

    @property
    def stdout(self) -> bytes:
        return self._user.stdout

    @property
    def stderr(self) -> bytes:
        return self._user.stderr

    @property
    def control(self) -> bytes | None:
        return bytes(self._control) if self._control_complete and not self._control_exceeded else None


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
    control: bytes | None = None


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
        committed_image = None
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
            committed_image = container.commit(repository=repository, tag="latest")
            return committed_image, run
        finally:
            if container is not None:
                try:
                    self._remove_container(container)
                except Exception:
                    if committed_image is not None:
                        try:
                            client.images.remove(committed_image.id, force=True)
                        except DockerException:
                            pass
                    raise

    def _run_case(self, image: str, command: list[str], message: dict, limits: Limits, pids: int) -> tuple[MonitoredRun, str]:
        container = None
        token = secrets.token_hex(24)
        payload = json.dumps({"token": token, **message}, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        try:
            options = container_options(memory_mb=limits.memory_mb, pids=pids, read_only=True)
            container = self._docker().containers.create(image, command=command, **options)
            outcome = self._monitor(
                container,
                timeout_seconds=limits.time_ms / 1000,
                output_limit=limits.output_kb * 1024,
                stdin=payload,
                control_token=token,
            )
            return outcome, token
        finally:
            if container is not None:
                self._remove_container(container)

    def _monitor(
        self,
        container,
        *,
        timeout_seconds: float,
        output_limit: int,
        stdin: bytes | None,
        control_token: str | None = None,
    ) -> MonitoredRun:
        collector = RuntimeOutputCollector(user_limit=output_limit, control_limit=CONTROL_LIMIT, token=control_token) if control_token else OutputCollector(output_limit)
        trigger: list[str | None] = [None]
        reader_error: list[Exception] = []
        wait_result: list[dict] = []
        wait_error: list[Exception] = []
        finished = threading.Event()
        attached = container.attach_socket(params={"stdout": 1, "stderr": 1, "stream": 1, "stdin": 0})
        input_attached = container.attach_socket(params={"stdout": 0, "stderr": 0, "stream": 1, "stdin": 1}) if stdin is not None else None

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

        raw = getattr(input_attached, "_sock", input_attached) if input_attached is not None else None
        if raw is not None:
            raw.settimeout(max(0.05, timeout_seconds))

        def writer() -> None:
            try:
                if stdin is not None:
                    raw.sendall(stdin)
            except OSError:
                pass

        started = time.monotonic()
        thread = threading.Thread(target=reader, name=f"runner-output-{container.id[:8]}", daemon=True)
        wait_thread = threading.Thread(target=waiter, name=f"runner-wait-{container.id[:8]}", daemon=True)
        writer_thread = threading.Thread(target=writer, name=f"runner-input-{container.id[:8]}", daemon=True) if stdin is not None else None
        try:
            container.start()
            thread.start()
            wait_thread.start()
            if writer_thread is not None:
                writer_thread.start()
            remaining = max(0.0, timeout_seconds - (time.monotonic() - started))
            if not finished.wait(remaining):
                if trigger[0] is None:
                    trigger[0] = "timeout"
                self._kill(container)
                finished.wait(5)
            wait_thread.join(timeout=1)
            thread.join(timeout=5)
            if isinstance(collector, RuntimeOutputCollector) and not collector.finish() and trigger[0] is None:
                trigger[0] = "output"
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
            control = collector.control if isinstance(collector, RuntimeOutputCollector) else None
            return MonitoredRun(status, collector.stdout, collector.stderr, exit_code, oom, elapsed, control)
        finally:
            if raw is not None:
                try:
                    raw.shutdown(socket.SHUT_RDWR)
                except (AttributeError, OSError):
                    pass
            if input_attached is not None:
                try:
                    input_attached.close()
                except Exception:
                    pass
            try:
                attached.close()
            except Exception:
                pass
            if writer_thread is not None:
                writer_thread.join()

    def _outcome_result(self, value: tuple[MonitoredRun, str], descriptor) -> dict:
        outcome, _token = value
        try:
            control = json.loads(outcome.control) if outcome.control is not None else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            control = None
        stdout, stderr = outcome.stdout, outcome.stderr
        if outcome.status in {"output_limit", "time_limit", "memory_limit"}:
            status = outcome.status
        elif isinstance(control, dict) and control.get("failure") == "memory_limit" and outcome.exit_code != 0:
            status = "memory_limit"
        else:
            status = classify_exit(trigger=None, oom_killed=outcome.oom_killed, exit_code=outcome.exit_code, has_control=isinstance(control, dict))
        result_value = None
        failure_kind = None
        time_ms = outcome.elapsed_ms
        memory_kb = 0
        if status == "ok" and isinstance(control, dict):
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
        elif status == "runtime_error" and isinstance(control, dict) and control.get("failure") == "return_type":
            failure_kind = "return_type"
        result = {
            "status": status,
            "value": result_value,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "time_ms": round(time_ms, 3),
            "memory_kb": memory_kb,
        }
        if failure_kind is not None:
            result["failure_kind"] = failure_kind
        return result

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
