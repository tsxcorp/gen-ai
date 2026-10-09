from __future__ import annotations

import asyncio
import socket
import threading
from collections import Counter

import httpx
import pytest
import requests
from google.auth.exceptions import RefreshError, TransportError

from app.adapters.base import PollResult, SubmitHandle
from app.adapters.factory import build_adapter
from app.adapters.vertex_common import VertexClient, VertexConfig
from app.context import AppContext
from app.core.events import EventHub
from app.core.expand import expand
from app.core.jobs import JobManager
from app.core.limiter import Limiter
from app.core.storage import Storage
from app.errors import AdapterError
from app.schemas import GenerationRequest, Sweep

URL = "https://aiplatform.googleapis.com/v1/synthetic"
SECRET = "private-key-token-secret-never-expose"
SETTINGS = {
    "maxAttempts": 3,
    "retryBaseSeconds": 0.001,
    "retryMaxSeconds": 0.002,
    "jobTimeoutSeconds": 2,
}


class Credentials:
    def __init__(self, *, valid=False, errors=(), gated=False):
        self.valid = valid
        self.token = "synthetic-token" if valid else None
        self.calls = 0
        self.errors = list(errors)
        self.started = threading.Event()
        self.release = threading.Event()
        self.requests = []
        if not gated:
            self.release.set()

    def refresh(self, request):
        self.calls += 1
        self.requests.append(request)
        self.started.set()
        if not self.release.wait(3):
            raise AssertionError("test did not release synthetic credential refresh")
        if self.errors:
            raise self.errors.pop(0)
        self.valid = True
        self.token = "synthetic-token"


def client_for(monkeypatch, creds, transport=None, timeout=120):
    monkeypatch.setattr(VertexClient, "_load_creds", lambda self: creds)
    http = httpx.AsyncClient(transport=httpx.MockTransport(transport or (lambda request: httpx.Response(200, json={}))))
    return VertexClient(VertexConfig("synthetic-project"), http, timeout)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real network forbidden in concurrency tests")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


async def test_32_parallel_token_callers_single_refresh(monkeypatch):
    creds = Credentials(gated=True)
    client = client_for(monkeypatch, creds)
    tasks = [asyncio.create_task(client.token()) for _ in range(32)]
    try:
        await until(creds.started.is_set)
        await asyncio.sleep(0.03)
        assert creds.calls == 1
        creds.release.set()
        assert await asyncio.gather(*tasks) == ["synthetic-token"] * 32
        assert creds.calls == 1
    finally:
        creds.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.aclose()


async def test_cancelled_waiter_does_not_duplicate_refresh(monkeypatch):
    creds = Credentials(gated=True)
    client = client_for(monkeypatch, creds)
    first = asyncio.create_task(client.token())
    tasks = [first]
    try:
        await until(creds.started.is_set)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        tasks.extend(asyncio.create_task(client.token()) for _ in range(8))
        await asyncio.sleep(0.03)
        assert creds.calls == 1
        creds.release.set()
        assert await asyncio.gather(*tasks[1:]) == ["synthetic-token"] * 8
    finally:
        creds.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.aclose()


async def test_valid_cached_token_does_not_schedule_thread(monkeypatch):
    creds = Credentials(valid=True)
    client = client_for(monkeypatch, creds)
    try:
        assert await client.token() == "synthetic-token"

        async def forbidden(*args, **kwargs):
            raise AssertionError("valid token must not enter a worker thread")

        with monkeypatch.context() as scoped:
            scoped.setattr(asyncio, "to_thread", forbidden)
            assert await asyncio.gather(*(client.token() for _ in range(32))) == ["synthetic-token"] * 32
        assert creds.calls == 0
    finally:
        await client.aclose()


async def test_close_waits_for_pending_refresh_and_closes_pools(monkeypatch):
    creds = Credentials(gated=True)
    sessions = []
    original = requests.Session

    class Session(original):
        def __init__(self):
            super().__init__()
            self.closes = 0
            sessions.append(self)

        def close(self):
            self.closes += 1
            super().close()

    monkeypatch.setattr(requests, "Session", Session)
    client = client_for(monkeypatch, creds)
    http = client.http
    waiter = asyncio.create_task(client.token())
    closing = None
    try:
        await until(creds.started.is_set)
        closing = asyncio.create_task(client.aclose())
        await asyncio.sleep(0.03)
        assert not closing.done()
        assert not http.is_closed
        creds.release.set()
        await waiter
        await closing
        assert http.is_closed
        assert len(sessions) == 1 and sessions[0].closes == 1
        await client.aclose()
        assert sessions[0].closes == 1
    finally:
        creds.release.set()
        await asyncio.gather(waiter, *([closing] if closing else []), return_exceptions=True)
        await client.aclose()


@pytest.mark.parametrize("timeout", [7, 120])
async def test_token_exchange_reuses_session_and_explicit_bounded_timeout(monkeypatch, timeout):
    seen = []

    def request(self, method, url, **kwargs):
        seen.append((self, kwargs.get("timeout")))
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"access_token":"synthetic-token"}'
        return response

    class Exchanging(Credentials):
        def refresh(self, request):
            request(url="https://oauth2.googleapis.com/token", method="POST", body=b"synthetic")
            super().refresh(request)

    monkeypatch.setattr(requests.Session, "request", request)
    creds = Exchanging()
    client = client_for(monkeypatch, creds, timeout=timeout)
    try:
        await client.token()
        creds.valid = False
        await client.token()
        assert len(seen) == 2
        assert seen[0][0] is seen[1][0]
        assert all(isinstance(bound, int | float) and 0 < bound <= min(timeout, 30) for _, bound in seen)
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "error,kind,before",
    [
        (TransportError(SECRET), "network", True),
        (RefreshError(SECRET, retryable=True), "network", True),
        (RefreshError(SECRET, retryable=False), "auth", False),
    ],
)
async def test_refresh_errors_sanitized_and_generation_not_called(monkeypatch, error, kind, before):
    calls = []
    client = client_for(monkeypatch, Credentials(errors=[error]), lambda request: calls.append(request))
    try:
        with pytest.raises(AdapterError) as caught:
            await client.request("POST", URL, {})
        assert caught.value.kind == kind
        if before:
            assert caught.value.before_send
        assert SECRET not in str(caught.value.args) + str(caught.value.body())
        assert calls == []
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "cause,reason",
    [
        (requests.exceptions.Timeout(SECRET), "timed out"),
        (requests.exceptions.SSLError(SECRET), "tls"),
        (requests.exceptions.ProxyError(SECRET), "proxy"),
        (requests.exceptions.ConnectionError(SECRET), "connection"),
        (socket.gaierror(SECRET), "dns"),
    ],
)
async def test_token_transport_reason_is_safe(monkeypatch, cause, reason):
    error = TransportError(SECRET)
    error.__cause__ = cause
    client = client_for(monkeypatch, Credentials(errors=[error]))
    try:
        with pytest.raises(AdapterError) as caught:
            await client.token()
        assert caught.value.kind == "network" and caught.value.before_send
        assert reason in caught.value.message.lower()
        assert SECRET not in str(caught.value.body()) + repr(caught.value.args)
    finally:
        await client.aclose()


async def test_failed_singleflight_can_refresh_again(monkeypatch):
    creds = Credentials(errors=[TransportError(SECRET)], gated=True)
    client = client_for(monkeypatch, creds)
    tasks = [asyncio.create_task(client.token()) for _ in range(8)]
    try:
        await until(creds.started.is_set)
        await asyncio.sleep(0.03)
        creds.release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert creds.calls == 1
        assert all(isinstance(result, AdapterError) and result.kind == "network" for result in results)
        assert await client.token() == "synthetic-token"
        assert creds.calls == 2
    finally:
        creds.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.aclose()


async def test_closed_client_cannot_restart_refresh(monkeypatch):
    creds = Credentials()
    client = client_for(monkeypatch, creds)
    await client.aclose()
    with pytest.raises((AdapterError, RuntimeError)):
        await client.token()
    assert creds.calls == 0


@pytest.mark.parametrize("fails", [False, True])
async def test_close_after_all_token_waiters_cancelled(monkeypatch, fails):
    creds = Credentials(gated=True, errors=[TransportError(SECRET)] if fails else [])
    client = client_for(monkeypatch, creds)
    http = client.http
    tasks = [asyncio.create_task(client.token()) for _ in range(8)]
    closing = None
    try:
        await until(creds.started.is_set)
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        closing = asyncio.create_task(client.aclose())
        await asyncio.sleep(0.03)
        assert not closing.done() and not http.is_closed
        creds.release.set()
        await asyncio.wait_for(closing, 2)
        assert creds.calls == 1 and http.is_closed
        await client.aclose()
    finally:
        creds.release.set()
        await asyncio.gather(*tasks, *([closing] if closing else []), return_exceptions=True)
        await client.aclose()


async def test_cancelled_close_waiter_does_not_abort_cleanup(monkeypatch):
    creds = Credentials(gated=True)
    client = client_for(monkeypatch, creds)
    http = client.http
    waiter = asyncio.create_task(client.token())
    closing = None
    try:
        await until(creds.started.is_set)
        closing = asyncio.create_task(client.aclose())
        await asyncio.sleep(0.03)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not http.is_closed
        creds.release.set()
        await waiter
        await asyncio.wait_for(client.aclose(), 2)
        assert http.is_closed and creds.calls == 1
    finally:
        creds.release.set()
        await asyncio.gather(waiter, *([closing] if closing else []), return_exceptions=True)
        await client.aclose()


async def test_existing_default_constructor_and_factory_remain_usable(monkeypatch, manifests):
    monkeypatch.setattr(VertexClient, "_load_creds", lambda self: Credentials(valid=True))
    client = VertexClient(VertexConfig("synthetic-project"))
    model = manifests["nano-banana-2.1"]
    adapter = build_adapter(model, {"vertex": {"projectId": "synthetic-project", "authMethod": "adc"}}, False)
    try:
        assert await client.token() == "synthetic-token"
        assert await adapter.client.token() == "synthetic-token"
    finally:
        await client.aclose()
        await adapter.client.aclose()


class RequestAdapter:
    poll_interval_s = 0

    def __init__(self, client):
        self.client = client
        self.calls = 0

    def build_payload(self, job):
        return {}

    async def submit(self, job):
        self.calls += 1
        await self.client.request("POST", URL, {})
        return SubmitHandle(job.id)

    async def poll(self, handle):
        return PollResult(state="done", outputs=[])

    async def download(self, outputs, dest):
        return []


def start_batch(manager, manifest, count=1):
    jobs = expand(manifest, GenerationRequest(model_id=manifest.id, prompt="synthetic"), Sweep(variants=count), 24)
    return manager.create_batch(jobs, {}, False, jobs[0].batch_id)


@pytest.mark.parametrize(
    "mode,attempts,generation_calls,status",
    [
        ("recover", 2, 1, "succeeded"),
        ("exhaust", 2, 0, "failed"),
        ("auth", 1, 0, "failed"),
        ("post_send", 1, 1, "failed"),
    ],
)
async def test_runner_token_retry_budget_without_double_billing(
    monkeypatch, manifests, tmp_path, mode, attempts, generation_calls, status
):
    calls = []

    def transport(request):
        calls.append(request)
        if mode == "post_send":
            raise httpx.ReadTimeout(SECRET)
        return httpx.Response(200, json={})

    errors = [TransportError(SECRET)] * (5 if mode == "exhaust" else 1)
    if mode == "auth":
        errors = [RefreshError(SECRET, retryable=False)]
    if mode == "post_send":
        errors = []
    client = client_for(monkeypatch, Credentials(errors=errors), transport)
    adapter = RequestAdapter(client)
    manifest = manifests["nano-banana-2.1"]
    manager = JobManager(manifests, Storage(tmp_path), EventHub(), lambda model: adapter, lambda: SETTINGS)
    try:
        batch = start_batch(manager, manifest)
        job = (await manager.wait_batch(batch.id, timeout=3)).jobs[0]
        assert job.status == status
        assert job.attempts == attempts and adapter.calls == attempts
        assert len(calls) == generation_calls
        if job.error:
            assert SECRET not in str(job.error)
    finally:
        await manager.shutdown()


class TrackedClient:
    def __init__(self):
        self.closes = 0

    async def aclose(self):
        self.closes += 1


class GatedAdapter(RequestAdapter):
    def __init__(self, client, active, peaks, release):
        super().__init__(client)
        self.active = active
        self.peaks = peaks
        self.release = release
        self.started = asyncio.Event()

    async def submit(self, job):
        self.calls += 1
        for key in (job.model_id, "provider"):
            self.active[key] += 1
            self.peaks[key] = max(self.peaks[key], self.active[key])
        self.started.set()
        try:
            await self.release.wait()
            assert self.client.closes == 0
            return SubmitHandle(job.id)
        finally:
            for key in (job.model_id, "provider"):
                self.active[key] -= 1


@pytest.mark.parametrize("grouped", [False, True])
async def test_cross_batch_model_and_provider_caps_and_done_cleanup(monkeypatch, manifests, tmp_path, grouped):
    template = manifests["nano-banana-2.1"]
    models = {}
    for index, cap in enumerate((2, 4, 4)):
        model = template.model_copy(deep=True)
        model.id = f"synthetic-{index}"
        model.limits.max_concurrent = cap
        model.limits.concurrency_group = "synthetic-group" if grouped else None
        models[model.id] = model
    active, peaks = Counter(), Counter()
    release = asyncio.Event()
    client = TrackedClient()
    adapters = {model.id: GatedAdapter(client, active, peaks, release) for model in models.values()}
    manager = JobManager(models, Storage(tmp_path), EventHub(), lambda model: adapters[model.id], lambda: SETTINGS)
    loaded = set()
    load_inputs = manager._load_inputs

    def recording_load(job):
        loaded.add(job.id)
        return load_inputs(job)

    monkeypatch.setattr(manager, "_load_inputs", recording_load)
    try:
        batches = [start_batch(manager, model, 6) for _ in range(2) for model in models.values()]
        await until(lambda: active["provider"] >= (2 if grouped else 4))
        await asyncio.sleep(0.03)
        assert peaks["provider"] <= (2 if grouped else 4)
        assert peaks["synthetic-0"] <= 2
        assert any(job.status == "queued" for job in manager.jobs.values())
        assert all(not job.inputs for job in manager.jobs.values() if job.status == "queued")
        assert all(job.id not in loaded for job in manager.jobs.values() if job.status == "queued")
        assert len(loaded) == (2 if grouped else 4)
        release.set()
        await asyncio.gather(*(manager.wait_batch(batch.id, timeout=3) for batch in batches))
        await until(lambda: not manager._tasks)
        assert all(job.status == "succeeded" for job in manager.jobs.values())
        assert peaks["provider"] <= (2 if grouped else 4)
        assert peaks["synthetic-0"] <= 2
    finally:
        release.set()
        await manager.shutdown()
    assert client.closes == 1


@pytest.mark.parametrize("phase", ["submit", "poll", "download"])
async def test_reset_retires_shared_client_only_after_last_active_lease(manifests, tmp_path, phase):
    models = [model for model in manifests.values() if model.provider == "vertex" and model.adapter == "vertex_image"][
        :2
    ]
    releases = [asyncio.Event() for _ in models]
    client = TrackedClient()

    class PhaseAdapter(GatedAdapter):
        async def submit(self, job):
            self.job = job
            if phase == "submit":
                return await super().submit(job)
            return SubmitHandle(job.id)

        async def poll(self, handle):
            if phase == "poll":
                await super().submit(self.job)
            return await super().poll(handle)

        async def download(self, outputs, dest):
            if phase == "download":
                await super().submit(self.job)
            return await super().download(outputs, dest)

    adapters = {
        model.id: PhaseAdapter(client, Counter(), Counter(), release)
        for model, release in zip(models, releases, strict=True)
    }
    manager = JobManager(manifests, Storage(tmp_path), EventHub(), lambda model: adapters[model.id], lambda: SETTINGS)
    try:
        batches = [start_batch(manager, model) for model in models]
        await asyncio.gather(*(adapter.started.wait() for adapter in adapters.values()))
        manager.reset_adapters("vertex")
        await asyncio.sleep(0.03)
        assert client.closes == 0
        releases[0].set()
        await manager.wait_batch(batches[0].id, timeout=3)
        assert client.closes == 0
        releases[1].set()
        await asyncio.gather(*(manager.wait_batch(batch.id, timeout=3) for batch in batches))
        await until(lambda: client.closes == 1)
    finally:
        for release in releases:
            release.set()
        await manager.shutdown()
    assert client.closes == 1 and not manager._tasks


async def test_shutdown_cancels_active_jobs_and_awaits_client_cleanup(manifests, tmp_path):
    close_started, finish_close = asyncio.Event(), asyncio.Event()

    class SlowClient(TrackedClient):
        async def aclose(self):
            self.closes += 1
            close_started.set()
            await finish_close.wait()

    client = SlowClient()
    adapter = GatedAdapter(client, Counter(), Counter(), asyncio.Event())
    manager = JobManager(manifests, Storage(tmp_path), EventHub(), lambda model: adapter, lambda: SETTINGS)
    batch = start_batch(manager, manifests["nano-banana-2.1"], 3)
    await adapter.started.wait()
    shutdown = asyncio.create_task(manager.shutdown())
    try:
        await asyncio.wait_for(close_started.wait(), 2)
        assert not shutdown.done()
        finish_close.set()
        await asyncio.wait_for(shutdown, 2)
        assert all(job.status == "canceled" for job in batch.jobs)
        assert not manager._tasks
        assert client.closes == 1
    finally:
        finish_close.set()
        await shutdown


async def test_model_rpm_spacing_preserved():
    limiter = Limiter()
    loop = asyncio.get_running_loop()
    starts = []

    async def work():
        async with limiter.slot("synthetic-model", 4, rpm=600):
            starts.append(loop.time())

    await asyncio.gather(*(work() for _ in range(3)))
    assert all(later - earlier >= 0.08 for earlier, later in zip(starts, starts[1:], strict=False))


@pytest.mark.parametrize("cancel", ["batch", "shutdown"])
@pytest.mark.parametrize("read_fails", [False, True])
async def test_cancellation_during_input_thread_drains_without_resurrecting_bytes(
    monkeypatch, manifests, tmp_path, cancel, read_fails
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    client = TrackedClient()
    adapter = GatedAdapter(client, Counter(), Counter(), asyncio.Event())
    storage = Storage(tmp_path)
    asset = storage.save_bytes(b"synthetic-reference-bytes", "image/png", "upload")
    original_read = storage.read_bytes

    def gated_read(asset_id):
        started.set()
        try:
            if not release.wait(3):
                raise AssertionError("test did not release input reader")
            if read_fails:
                raise OSError("synthetic read failure during cancellation")
            return original_read(asset_id)
        finally:
            finished.set()

    monkeypatch.setattr(storage, "read_bytes", gated_read)
    manager = JobManager(manifests, storage, EventHub(), lambda model: adapter, lambda: SETTINGS)
    manifest = manifests["nano-banana-2.1"]
    jobs = expand(manifest, GenerationRequest(model_id=manifest.id, prompt="synthetic"), None, 24)
    job = jobs[0]
    job.assets_in = {"reference": asset.id}
    batch = manager.create_batch(jobs, {}, False, job.batch_id)
    shutdown = None
    try:
        await until(started.is_set)
        manager.reset_adapters("vertex")
        if cancel == "batch":
            manager.cancel_batch(batch.id)
        shutdown = asyncio.create_task(manager.shutdown())
        await asyncio.sleep(0.03)
        assert not shutdown.done()
        assert client.closes == 0
        assert not job.inputs and not finished.is_set()
        assert adapter.calls == 0 and job.attempts == 0
        release.set()
        await asyncio.wait_for(shutdown, 2)
        await asyncio.sleep(0)
        assert finished.is_set()
        assert job.status == "canceled" and not job.inputs
        assert adapter.calls == 0 and job.attempts == 0
        assert client.closes == 1 and not manager._tasks
        assert not manager._input_tasks
    finally:
        release.set()
        if shutdown:
            await asyncio.gather(shutdown, return_exceptions=True)
        await manager.shutdown()


@pytest.mark.parametrize("cancel_fails", [False, True])
async def test_remote_cancel_retains_retired_client_until_shutdown_cleanup(manifests, tmp_path, cancel_fails):
    polling, cancel_started, cancel_interrupted, finish_cancel = (asyncio.Event() for _ in range(4))
    client = TrackedClient()

    class RemoteAdapter(RequestAdapter):
        async def submit(self, job):
            self.calls += 1
            return SubmitHandle("synthetic-accepted-operation")

        async def poll(self, handle):
            polling.set()
            await asyncio.Event().wait()

        async def cancel(self, handle):
            assert handle.id == "synthetic-accepted-operation"
            cancel_started.set()
            try:
                await finish_cancel.wait()
            except asyncio.CancelledError:
                cancel_interrupted.set()
                await finish_cancel.wait()
            assert client.closes == 0
            if cancel_fails:
                raise OSError("synthetic remote cancel cleanup failure")

    adapter = RemoteAdapter(client)
    manager = JobManager(manifests, Storage(tmp_path), EventHub(), lambda model: adapter, lambda: SETTINGS)
    batch = start_batch(manager, manifests["nano-banana-2.1"])
    shutdown = None
    try:
        await asyncio.wait_for(polling.wait(), 2)
        manager.reset_adapters("vertex")
        manager.cancel_batch(batch.id)
        await asyncio.wait_for(cancel_started.wait(), 2)
        await until(lambda: not manager._tasks)
        assert client.closes == 0 and adapter.calls == 1
        shutdown = asyncio.create_task(manager.shutdown())
        await asyncio.wait_for(cancel_interrupted.wait(), 2)
        assert not shutdown.done() and client.closes == 0
        finish_cancel.set()
        await asyncio.wait_for(shutdown, 2)
        assert client.closes == 1 and not manager._remote_tasks
        assert batch.jobs[0].status == "canceled" and adapter.calls == 1
    finally:
        finish_cancel.set()
        if shutdown:
            await asyncio.gather(shutdown, return_exceptions=True)
        await manager.shutdown()


async def test_old_and_new_client_generations_share_same_provider_cap(manifests, tmp_path):
    template = manifests["nano-banana-2.1"]
    models = {}
    for index, cap in enumerate((2, 4)):
        model = template.model_copy(deep=True)
        model.id = f"synthetic-generation-{index}"
        model.limits.max_concurrent = cap
        model.limits.concurrency_group = None
        models[model.id] = model
    small, broad = models.values()
    active, peaks = Counter(), Counter()
    old_release, new_release = asyncio.Event(), asyncio.Event()
    old_client, new_client = TrackedClient(), TrackedClient()
    old_adapters = {model.id: GatedAdapter(old_client, active, peaks, old_release) for model in models.values()}
    new_adapters = {model.id: GatedAdapter(new_client, active, peaks, new_release) for model in models.values()}
    current = old_adapters
    manager = JobManager(models, Storage(tmp_path), EventHub(), lambda model: current[model.id], lambda: SETTINGS)
    try:
        old_batch = start_batch(manager, small, 2)
        await until(lambda: active["provider"] == 2)
        manager.reset_adapters("vertex")
        current = new_adapters
        new_batches = [start_batch(manager, broad, 6), start_batch(manager, small, 4)]
        await until(lambda: active["provider"] == 4)
        await asyncio.sleep(0.03)
        assert peaks["provider"] == 4 and peaks[small.id] == 2
        assert old_client.closes == 0 and new_client.closes == 0
        assert manager._adapter(small).client is new_client
        old_release.set()
        await manager.wait_batch(old_batch.id, timeout=3)
        await until(lambda: old_client.closes == 1)
        assert new_client.closes == 0
        new_release.set()
        await asyncio.gather(*(manager.wait_batch(batch.id, timeout=3) for batch in new_batches))
        assert peaks["provider"] == 4 and peaks[small.id] == 2
        assert all(job.status == "succeeded" for job in manager.jobs.values())
    finally:
        old_release.set()
        new_release.set()
        await manager.shutdown()
    assert old_client.closes == 1 and new_client.closes == 1


async def test_poll_token_failure_never_resubmits_accepted_generation(monkeypatch, manifests, tmp_path):
    generation = []
    creds = Credentials()
    client = client_for(monkeypatch, creds, lambda request: generation.append(request) or httpx.Response(200, json={}))

    class PollAuthAdapter(RequestAdapter):
        async def submit(self, job):
            await super().submit(job)
            creds.valid = False
            creds.errors = [TransportError(SECRET)] * 10
            return SubmitHandle("synthetic-accepted-operation")

        async def poll(self, handle):
            await self.client.request("GET", URL)
            return PollResult(state="running")

    adapter = PollAuthAdapter(client)
    manager = JobManager(manifests, Storage(tmp_path), EventHub(), lambda model: adapter, lambda: SETTINGS)
    try:
        batch = start_batch(manager, manifests["nano-banana-2.1"])
        job = (await manager.wait_batch(batch.id, timeout=3)).jobs[0]
        assert job.status == "failed" and job.error.kind == "network"
        assert job.operation_id == "synthetic-accepted-operation"
        assert adapter.calls == 1 and job.attempts == 1
        assert len(generation) == 1 and generation[0].method == "POST"
        assert 2 <= creds.calls <= 5
        assert SECRET not in job.error.message
    finally:
        await manager.shutdown()


async def test_context_clients_shared_isolated_and_targeted_reset(monkeypatch, manifests, tmp_path):
    monkeypatch.setattr(VertexClient, "_load_creds", lambda self: Credentials(valid=True))
    context = AppContext(data_dir=tmp_path / "data", tmp_dir=tmp_path / "tmp", demo=False)
    providers = {
        "vertex": {"projectId": "synthetic-project", "authMethod": "adc"},
        "openai": {"apiKey": "synthetic-not-a-real-key"},
    }
    monkeypatch.setattr(context.config, "providers", lambda: providers)
    models = [model for model in manifests.values() if model.provider == "vertex" and model.adapter == "vertex_image"][
        :2
    ]
    try:
        first = context.jobs._adapter(models[0]).client
        second = context.jobs._adapter(models[1]).client
        assert first is second
        other_model = next(model for model in manifests.values() if model.provider == "openai")
        other_client = context.jobs._adapter(other_model).client
        assert other_client is not first
        context.reset_adapters("openai")
        assert context.jobs._adapter(models[0]).client is first
        assert context.jobs._adapter(other_model).client is not other_client
        context.reset_adapters("vertex")
        replacement = context.jobs._adapter(models[0]).client
        assert replacement is not first
        assert context.jobs._adapter(models[1]).client is replacement
        standalone = build_adapter(models[0], providers, False)
        assert standalone.client is not replacement
        await standalone.client.aclose()
    finally:
        await context.shutdown()
