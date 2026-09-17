from __future__ import annotations

import io
import tarfile

import pytest

from runner.engine import OutputCollector, build_archive, classify_exit, container_options


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
