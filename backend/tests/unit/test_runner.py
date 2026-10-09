from __future__ import annotations

import asyncio
import random

import pytest

from app.adapters.base import PollResult, SubmitHandle
from app.adapters.demo import DemoAdapter
from app.core.events import EventHub
from app.core.expand import expand
from app.core.jobs import JobManager, backoff_delay
from app.core.storage import Storage
from app.errors import AdapterError
from app.schemas import GenerationRequest, Sweep

SETTINGS = {"maxAttempts": 4, "retryBaseSeconds": 0.01, "retryMaxSeconds": 0.05, "jobTimeoutSeconds": 5}


class Scripted(DemoAdapter):
    """Demo adapter whose submit() follows a script of exceptions/None per call."""

    def __init__(self, m, script):
        super().__init__(m)
        self.script = list(script)
        self.calls = 0
        self.inflight = 0
        self.peak = 0

    async def submit(self, job):
        self.calls += 1
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        try:
            await asyncio.sleep(0.03)
            step = self.script.pop(0) if self.script else None
            if step:
                raise step
            return SubmitHandle(id=job.id, data={"outputs": []})
        finally:
            self.inflight -= 1

    async def poll(self, handle):
        from app.adapters.base import OutputRef
        from app.adapters.demo import make_png

        return PollResult(state="done", outputs=[OutputRef("image/png", make_png(16, 16, "x"))])


def make(manifests, tmp_path, script, model="nano-banana-2.1", settings=SETTINGS):
    m = manifests[model]
    ad = Scripted(m, script)
    mgr = JobManager(manifests, Storage(tmp_path), EventHub(), lambda _m: ad, lambda: dict(settings))
    return m, ad, mgr


def batch(m, mgr, n=1):
    jobs = expand(m, GenerationRequest(model_id=m.id, prompt="p"), Sweep(variants=n), 24)
    return mgr.create_batch(jobs, {}, False, jobs[0].batch_id)


async def test_quota_retried_then_succeeds(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [AdapterError("quota", "429"), AdapterError("quota", "429")])
    b = await mgr.wait_batch(batch(m, mgr).id)
    j = b.jobs[0]
    assert j.status == "succeeded" and j.attempts == 3 and len(j.assets) == 1


async def test_quota_gives_up_after_max_attempts(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [AdapterError("quota", "429")] * 10)
    j = (await mgr.wait_batch(batch(m, mgr).id)).jobs[0]
    assert j.status == "failed" and j.error.kind == "quota" and ad.calls == 4


@pytest.mark.parametrize("kind,status", [("blocked", "blocked"), ("invalid", "failed"), ("auth", "failed")])
async def test_never_auto_retried(manifests, tmp_path, kind, status):
    m, ad, mgr = make(manifests, tmp_path, [AdapterError(kind, "x")] * 5)
    j = (await mgr.wait_batch(batch(m, mgr).id)).jobs[0]
    assert j.status == status and j.attempts == 1 and ad.calls == 1


async def test_network_after_send_is_not_resubmitted(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [AdapterError("network", "x")] * 5)
    j = (await mgr.wait_batch(batch(m, mgr).id)).jobs[0]
    assert j.status == "failed" and ad.calls == 1  # the request may have been accepted: never resubmit


async def test_network_before_send_bounded_retry(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [AdapterError("network", "x", before_send=True)] * 5)
    j = (await mgr.wait_batch(batch(m, mgr).id)).jobs[0]
    assert j.status == "failed" and ad.calls == 2


async def test_per_model_concurrency_limit(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [])
    m.limits.max_concurrent = 2
    await mgr.wait_batch(batch(m, mgr, 6).id)
    assert ad.peak == 2 and mgr.limiter.peak[m.id] == 2


async def test_cancel_queued_and_running(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [])
    m.limits.max_concurrent = 1
    b = batch(m, mgr, 3)
    await asyncio.sleep(0.01)
    mgr.cancel_batch(b.id)
    b = await mgr.wait_batch(b.id)
    assert [j.status for j in b.jobs] == ["canceled"] * 3
    assert b.jobs[0].best_effort_cancel and not b.jobs[2].best_effort_cancel


async def test_retry_creates_new_job_only_for_failed(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [AdapterError("blocked", "x")])
    b = await mgr.wait_batch(batch(m, mgr).id)
    new = mgr.retry_job(b.jobs[0].id)
    assert new.id != b.jobs[0].id and len(mgr.get_batch(b.id).jobs) == 2
    b = await mgr.wait_batch(b.id)
    assert new.status == "succeeded"
    with pytest.raises(Exception, match="only failed"):
        mgr.retry_job(new.id)


async def test_terminal_state_is_final(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [])
    j = (await mgr.wait_batch(batch(m, mgr).id)).jobs[0]
    mgr._set(j, "running")
    assert j.status == "succeeded"


async def test_events_published(manifests, tmp_path):
    m, ad, mgr = make(manifests, tmp_path, [])
    q = mgr.hub.subscribe()
    await mgr.wait_batch(batch(m, mgr).id)
    names = []
    while not q.empty():
        names.append(q.get_nowait()[1])
    assert "job.updated" in names and "batch.updated" in names


def test_backoff_has_jitter_and_cap():
    rng = random.Random(1)
    vals = {backoff_delay(2, 1.0, 10.0, rng) for _ in range(20)}
    assert len(vals) > 5 and all(1.0 <= v <= 3.0 for v in vals)
    assert backoff_delay(20, 1.0, 10.0) == 10.0
