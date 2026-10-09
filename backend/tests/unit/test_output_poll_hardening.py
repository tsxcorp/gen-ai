from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters import base
from app.adapters.base import OutputRef, PollResult, SubmitHandle, write_outputs
from app.adapters.http_common import HardenedClient
from app.adapters.vertex_common import VertexClient, VertexConfig
from app.core import jobs as jobs_module
from app.core.events import EventHub
from app.core.expand import expand
from app.core.jobs import JobManager
from app.core.storage import Storage
from app.errors import AdapterError
from app.schemas import GenerationRequest, Sweep


@pytest.mark.parametrize("writer_name,encoded", [("_write_bytes", False), ("_write_b64", True)])
@pytest.mark.parametrize("fail_worker", [False, True])
async def test_cancel_drains_output_worker_before_cleanup(tmp_path, monkeypatch, writer_name, encoded, fail_worker):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original = getattr(base, writer_name)
    calls = 0

    def gated_writer(path, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(path, data)
        path.write_bytes(b"partial-current-output")
        started.set()
        try:
            if not release.wait(2):
                raise RuntimeError("test worker gate timed out")
            if fail_worker:
                raise OSError("synthetic disk failure")
            return original(path, data)
        finally:
            finished.set()

    monkeypatch.setattr(base, writer_name, gated_writer)
    sentinel = tmp_path / "unrelated.txt"
    sentinel.write_bytes(b"keep")
    outputs = [OutputRef("image/png", b64="Zmlyc3Q="), OutputRef("image/png", b64="c2Vjb25k")]
    if not encoded:
        outputs = [OutputRef("image/png", data=b"first"), OutputRef("image/png", data=b"second")]
    task = asyncio.create_task(write_outputs(outputs, tmp_path))
    try:
        assert await asyncio.to_thread(started.wait, 1), "output thread never started"
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "cancellation returned while output worker still owned the file"
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "repeated cancellation bypassed worker drain"
        assert not finished.is_set()
        assert len(list(tmp_path.iterdir())) == 3, "cleanup raced the live worker"
    finally:
        release.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), 1)
        except asyncio.CancelledError:
            pass
    assert task.cancelled(), "worker failure must not replace requested cancellation"
    assert finished.is_set()
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"keep"


@pytest.mark.parametrize("writer_name,encoded", [("_write_bytes", False), ("_write_b64", True)])
async def test_worker_failure_removes_current_and_completed_outputs(tmp_path, monkeypatch, writer_name, encoded):
    original = getattr(base, writer_name)
    calls = 0

    def failing_writer(path, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(path, data)
        path.write_bytes(b"partial")
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(base, writer_name, failing_writer)
    outputs = [OutputRef("image/png", b64="Zmlyc3Q="), OutputRef("image/png", b64="c2Vjb25k")]
    if not encoded:
        outputs = [OutputRef("image/png", data=b"first"), OutputRef("image/png", data=b"second")]
    with pytest.raises(OSError, match="synthetic disk failure"):
        await asyncio.wait_for(write_outputs(outputs, tmp_path), 1)
    assert not list(tmp_path.iterdir())


async def test_uri_failure_cleans_current_and_prior_output_without_touching_other_files(tmp_path):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_bytes(b"keep")

    async def fetch(uri, path):
        path.write_bytes(b"partial-stream")
        raise AdapterError("network", "synthetic interrupted stream")

    with pytest.raises(AdapterError, match="synthetic interrupted stream"):
        await write_outputs([OutputRef("image/png", data=b"first"), OutputRef("image/png", uri="local://output")], tmp_path, fetch)
    assert list(tmp_path.iterdir()) == [sentinel]


async def test_success_preserves_original_bytes_and_hash(tmp_path):
    payload = b"original-watermarked-output\x00\xff"
    files = await write_outputs([OutputRef("image/png", data=payload)], tmp_path)
    assert len(files) == 1
    assert files[0].path.read_bytes() == payload
    assert files[0].size_bytes == len(payload)
    assert files[0].sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("client_kind", ["http", "vertex"])
@pytest.mark.parametrize("fail_worker", [False, True])
async def test_stream_cancel_drains_chunk_before_file_close_and_unlink(tmp_path, monkeypatch, client_kind, fail_worker):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    dest = tmp_path / "streamed-output.bin"
    sentinel = tmp_path / "keep.txt"
    sentinel.write_bytes(b"keep")
    original_open = Path.open
    closed_after_worker = []
    response_exit_after_worker = []
    requests = []

    class GatedFile:
        def __init__(self):
            self.file = original_open(dest, "wb")
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed_after_worker.append(finished.is_set())
            self.file.close()

        def write(self, chunk):
            self.calls += 1
            if self.calls == 1:
                size = self.file.write(chunk)
                self.file.flush()
                return size
            started.set()
            try:
                if not release.wait(2):
                    raise RuntimeError("test chunk gate timed out")
                assert not self.file.closed, "stream file was closed while its write thread was active"
                if fail_worker:
                    raise OSError("synthetic chunk write failure")
                return self.file.write(chunk)
            finally:
                finished.set()

    def open_file(path, mode="r", *args, **kwargs):
        if path == dest and mode == "wb":
            return GatedFile()
        return original_open(path, mode, *args, **kwargs)

    class LocalResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            response_exit_after_worker.append(finished.is_set())

        async def aiter_bytes(self, chunk_size):
            yield b"first-original-chunk"
            yield b"second-original-chunk"

    class LocalHTTP:
        def stream(self, method, url, **kwargs):
            requests.append((method, url))
            return LocalResponse()

    async def local_headers(self):
        return {}

    monkeypatch.setattr(Path, "open", open_file)
    if client_kind == "vertex":
        monkeypatch.setattr(VertexClient, "_auth_headers", local_headers)
        client = VertexClient(VertexConfig("synthetic-project"), http=LocalHTTP())
    else:
        client = HardenedClient("local-test", {}, lambda url: None,
                                lambda status, body: AdapterError("invalid", "local response"), http=LocalHTTP())
    task = asyncio.create_task(client.stream_to_file("https://storage.googleapis.com/local-only", dest))
    try:
        assert await asyncio.to_thread(started.wait, 1), "stream chunk writer never started"
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "stream cancellation returned before chunk worker ended"
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "repeated cancellation bypassed stream drain"
        assert not closed_after_worker and not response_exit_after_worker
        assert dest.exists(), "partial stream was unlinked while writer still ran"
        assert not finished.is_set()
    finally:
        release.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), 1)
        except asyncio.CancelledError:
            pass
    assert task.cancelled()
    assert finished.is_set()
    assert closed_after_worker == [True]
    assert response_exit_after_worker == [True]
    assert not dest.exists()
    assert sentinel.read_bytes() == b"keep"
    assert len(requests) == 1


class PollAdapter:
    poll_interval_s = 0.0

    def __init__(self, poll):
        self.poll_impl = poll
        self.submit_calls = 0
        self.poll_handles = []
        self.download_calls = 0

    def build_payload(self, job):
        return {}

    async def submit(self, job):
        self.submit_calls += 1
        return SubmitHandle("operations/independent-hardening-test")

    async def poll(self, handle):
        self.poll_handles.append(handle)
        return await self.poll_impl()

    async def download(self, outputs, dest):
        self.download_calls += 1
        return await write_outputs(outputs, dest)


def runner(manifests, tmp_path, adapter, **overrides):
    settings = {"maxAttempts": 2, "retryBaseSeconds": 0.001, "retryMaxSeconds": 0.002,
                "jobTimeoutSeconds": 1, "pollIntervalSeconds": 0.01, **overrides}
    manifest = manifests["nano-banana-2.1"].model_copy(deep=True)
    manager = JobManager(manifests, Storage(tmp_path), EventHub(), lambda _manifest: adapter, lambda: dict(settings))
    job = expand(manifest, GenerationRequest(model_id=manifest.id, prompt="independent test"), Sweep(), 24)[0]
    return manager, manifest, job


def controlled_clock(monkeypatch):
    clock = SimpleNamespace(now=0.0, sleeps=[])

    class AsyncioBoundary:
        def __getattr__(self, name):
            return getattr(asyncio, name)

        async def sleep(self, delay):
            clock.sleeps.append(delay)
            clock.now += delay
            await asyncio.sleep(0)

    monkeypatch.setattr(jobs_module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(jobs_module, "asyncio", AsyncioBoundary())
    monkeypatch.setattr(jobs_module.random, "uniform", lambda lower, upper: 1.0)
    return clock


def assert_timeout(job, adapter):
    assert job.status == "failed"
    assert job.error.kind == "timeout"
    assert job.operation_id == "operations/independent-hardening-test"
    assert job.operation_id in job.error.message
    assert adapter.submit_calls == 1
    assert adapter.download_calls == 0
    assert not job.assets


async def test_job_cancellation_keeps_slot_and_client_lease_until_output_worker_finishes(manifests, tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    closed = []

    async def close_client():
        closed.append(finished.is_set())

    def gated_writer(path, data):
        path.write_bytes(b"partial")
        started.set()
        try:
            if not release.wait(2):
                raise RuntimeError("test worker gate timed out")
            path.write_bytes(data)
            return len(data), hashlib.sha256(data).hexdigest()
        finally:
            finished.set()

    async def poll():
        return PollResult("done", [OutputRef("image/png", data=b"original")])

    monkeypatch.setattr(base, "_write_bytes", gated_writer)
    adapter = PollAdapter(poll)
    adapter.client = SimpleNamespace(aclose=close_client)
    manager, manifest, job = runner(manifests, tmp_path, adapter)
    manager.create_batch([job], {}, False, job.batch_id)
    task = manager._tasks[job.id]
    slot_key = manifest.limits.concurrency_group or manifest.id
    try:
        assert await asyncio.to_thread(started.wait, 1)
        manager.reset_adapters()
        manager.cancel_batch(job.batch_id)
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()
        assert manager.limiter.active[slot_key] == 1
        assert manager.provider_limiter.active[manifest.provider] == 1
        assert manager._leases[id(adapter.client)] == 1
        assert not closed
        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()
        assert manager._leases[id(adapter.client)] == 1
    finally:
        release.set()
        await asyncio.wait_for(asyncio.shield(task), 1)
        await asyncio.wait_for(manager.shutdown(), 1)
    assert finished.is_set()
    assert job.status == "canceled" and job.best_effort_cancel
    assert manager.limiter.active[slot_key] == 0
    assert manager.provider_limiter.active[manifest.provider] == 0
    assert not manager._leases
    assert closed == [True]
    assert not list(manager.storage.run_dir.glob("*.png"))
    assert adapter.submit_calls == 1


@pytest.mark.parametrize("phase", ["interval", "backoff"])
async def test_poll_never_starts_after_deadline_or_oversleeps(manifests, tmp_path, monkeypatch, phase):
    clock = controlled_clock(monkeypatch)
    starts = []

    async def poll():
        starts.append(clock.now)
        if phase == "backoff":
            raise AdapterError("network", "synthetic poll failure")
        return PollResult("running")

    adapter = PollAdapter(poll)
    adapter.poll_interval_s = 3.0
    manager, manifest, job = runner(manifests, tmp_path, adapter, retryBaseSeconds=3, retryMaxSeconds=3)
    await asyncio.wait_for(manager._attempt(job, manifest), 1)
    assert_timeout(job, adapter)
    assert starts == [0.0]
    assert all(delay <= 1 for delay in clock.sleeps)
    assert clock.now <= 1


async def test_done_after_deadline_is_not_downloaded(manifests, tmp_path, monkeypatch):
    clock = controlled_clock(monkeypatch)

    async def poll():
        clock.now = 1.01
        return PollResult("done", [OutputRef("image/png", data=b"late-output")])

    adapter = PollAdapter(poll)
    manager, manifest, job = runner(manifests, tmp_path, adapter)
    await asyncio.wait_for(manager._attempt(job, manifest), 1)
    assert_timeout(job, adapter)
    assert len(adapter.poll_handles) == 1


@pytest.mark.parametrize("return_done_on_cancel", [False, True])
async def test_hung_poll_has_remaining_time_timeout_and_rejects_late_done(manifests, tmp_path, return_done_on_cancel):
    canceled = asyncio.Event()

    async def poll():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            canceled.set()
            if return_done_on_cancel:
                return PollResult("done", [OutputRef("image/png", data=b"late")])
            raise

    adapter = PollAdapter(poll)
    manager, manifest, job = runner(manifests, tmp_path, adapter, jobTimeoutSeconds=0.04)
    await asyncio.wait_for(manager._attempt(job, manifest), 1)
    assert canceled.is_set()
    assert_timeout(job, adapter)
    assert len(adapter.poll_handles) == 1


@pytest.mark.parametrize("max_attempts", [1, 2, 4])
async def test_post_submit_retry_budget_is_extra_retries_on_same_handle(manifests, tmp_path, max_attempts):
    async def poll():
        raise AdapterError("network", "synthetic persistent poll failure")

    adapter = PollAdapter(poll)
    manager, manifest, job = runner(manifests, tmp_path, adapter, maxAttempts=max_attempts)
    await asyncio.wait_for(manager._attempt(job, manifest), 1)
    assert job.status == "failed" and job.error.kind == "network"
    assert len(adapter.poll_handles) == 1 + max(2, max_attempts)
    assert all(handle is adapter.poll_handles[0] for handle in adapter.poll_handles)
    assert adapter.submit_calls == 1 and adapter.download_calls == 0
    assert job.operation_id == "operations/independent-hardening-test"
