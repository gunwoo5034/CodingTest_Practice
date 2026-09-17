from __future__ import annotations

import io
import json
import tarfile

import pytest
from docker.errors import APIError

from runner.engine import DockerRunner, DockerUnavailable, MonitoredRun, OutputCollector, RuntimeOutputCollector, build_archive, classify_exit, container_options
from runner.models import Limits
from runner.wrappers import Bundle


def test_archive_is_deterministic_owned_by_sandbox_user_and_bounded():
    first = build_archive({"b.txt": b"b", "a.txt": b"a"}, max_bytes=100)
    second = build_archive({"a.txt": b"a", "b.txt": b"b"}, max_bytes=100)
    assert first == second
    with tarfile.open(fileobj=io.BytesIO(first), mode="r:") as archive:
        members = archive.getmembers()
        assert [item.name for item in members] == ["a.txt", "b.txt"]
        assert {(item.uid, item.gid, item.mtime) for item in members} == {(10001, 10001, 0)}

    with pytest.raises(ValueError):
        build_archive({"large": b"x" * 101}, max_bytes=100)


def test_output_collector_stops_while_combined_stream_exceeds_limit():
    collector = OutputCollector(limit=5)
    assert collector.add("stdout", b"abc") is True
    assert collector.add("stderr", b"de") is True
    assert collector.add("stdout", b"f") is False
    assert collector.exceeded is True
    assert collector.stdout == b"abc"
    assert collector.stderr == b"de"


def test_private_result_frame_is_bounded_and_excluded_across_split_marker_chunks():
    collector = RuntimeOutputCollector(user_limit=5, control_limit=100, token="token")
    assert collector.add("stderr", b"abc\n__LOOP") is True
    assert collector.add("stderr", b"CODE_RESULT__token:") is True
    assert collector.add("stderr", b'{"value":"large",') is True
    assert collector.add("stderr", b'"time_ms":1}\n') is True
    collector.finish()

    assert collector.stderr == b"abc"
    assert collector.control == b'{"value":"large","time_ms":1}'
    assert collector.exceeded is False


def test_private_result_frame_has_an_independent_size_limit():
    collector = RuntimeOutputCollector(user_limit=3, control_limit=4, token="token")
    assert collector.add("stderr", b"abc\n__LOOPCODE_RESULT__token:12345") is False

    assert collector.stderr == b"abc"
    assert collector.control is None
    assert collector.exceeded is True


@pytest.mark.parametrize(
    ("trigger", "oom", "exit_code", "has_control", "expected"),
    [
        ("output", True, 137, False, "output_limit"),
        ("timeout", True, 137, False, "time_limit"),
        (None, True, 137, False, "memory_limit"),
        (None, False, 1, False, "runtime_error"),
        (None, False, 0, False, "system_error"),
        (None, False, 0, True, "ok"),
    ],
)
def test_exit_classification_has_deterministic_priority(trigger, oom, exit_code, has_control, expected):
    assert classify_exit(trigger=trigger, oom_killed=oom, exit_code=exit_code, has_control=has_control) == expected


@pytest.mark.parametrize(
    ("manager_status", "expected"),
    [
        ("runtime_error", "memory_limit"),
        ("output_limit", "output_limit"),
        ("time_limit", "time_limit"),
        ("memory_limit", "memory_limit"),
    ],
)
def test_manager_limits_take_priority_over_harness_memory_signal(manager_status, expected):
    control = json.dumps({"failure": "memory_limit"}).encode()
    outcome = MonitoredRun(manager_status, b"", b"", 1, manager_status == "memory_limit", 1.0, control)

    result = DockerRunner()._outcome_result((outcome, "token"), None)

    assert result["status"] == expected


def test_runtime_container_has_no_mounts_or_network_and_uses_read_only_root():
    options = container_options(memory_mb=256, pids=64, read_only=True)
    assert options["network_disabled"] is True
    assert options["read_only"] is True
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["labels"] == {"com.loopcode.sandbox": "true"}
    assert options["memswap_limit"] == "256m"
    assert options["pids_limit"] == 64
    assert "volumes" not in options
    assert "mounts" not in options
    assert "environment" not in options


def test_committed_image_is_removed_when_staging_cleanup_fails():
    class Image:
        id = "committed-image"

    class Container:
        id = "stage-container"

        def put_archive(self, path, archive):
            return True

        def get_archive(self, path):
            return iter([b"artifact"]), {}

        def commit(self, **kwargs):
            return Image()

        def remove(self, force):
            raise APIError("staging cleanup failed")

    class Containers:
        def create(self, *args, **kwargs):
            return Container()

    class Images:
        def __init__(self):
            self.removed = []

        def remove(self, image, force):
            self.removed.append((image, force))

    class Client:
        containers = Containers()
        images = Images()

    client = Client()
    runner = DockerRunner(client)
    runner._monitor = lambda *args, **kwargs: MonitoredRun("ok", b"", b"", 0, False, 1.0)
    bundle = Bundle("sandbox", {"source": b"source"}, ["compile"], ["run"])

    with pytest.raises(DockerUnavailable):
        runner._prepare_image(bundle, Limits(time_ms=100, memory_mb=256, output_kb=64))

    assert client.images.removed == [("committed-image", True)]
