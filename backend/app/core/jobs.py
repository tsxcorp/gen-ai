"""Batch/Job state machine + asyncio runner.

queued -> running -> succeeded | failed | blocked | canceled (monotone; retry creates a NEW job).
Retry rules (invariants 5 and 14):
- `submit` is retried only while no operation handle exists AND the error is `quota` (not accepted, free) or a
  connection failure that provably happened before the request was sent. Never after a handle was returned.
- After submit, transient errors (network/timeout/quota) only retry `poll` / `download` on the SAME operation,
  bounded; a poll timeout ends the job as failed(timeout) carrying the operation id. No resubmit, ever.
- `blocked` and `invalid` are never retried automatically.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any, Protocol, cast

from app.adapters.base import ProviderAdapter
from app.core.cost import estimate_job_ex
from app.core.events import EventHub
from app.core.limiter import Limiter
from app.core.storage import Storage
from app.errors import AdapterError, ApiError
from app.schemas import TERMINAL, Batch, InputAsset, Job, JobError, ModelManifest, now_iso

log = logging.getLogger("aigen.jobs")
TRANSIENT = {"network", "timeout", "quota"}  # retried on poll/download only (same operation)

class CloseableClient(Protocol):
    async def aclose(self) -> None: ...


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random | None = None) -> float:
    """Exponential backoff with full-ish jitter: base*2^(attempt-1) scaled by U(0.5,1.5), capped."""
    r = (rng or random).uniform(0.5, 1.5)
    return min(cap, base * (2 ** (attempt - 1)) * r)


class JobManager:
    def __init__(
        self,
        manifests: dict[str, ModelManifest],
        storage: Storage,
        hub: EventHub,
        adapter_for: Callable[[ModelManifest], ProviderAdapter],
        settings: Callable[[], dict[str, Any]],
        prices: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.manifests = manifests
        self.storage = storage
        self.hub = hub
        self.adapter_for = adapter_for
        self.settings = settings
        self.prices = prices
        self.limiter = Limiter()
        self.model_limiter = Limiter()
        self.provider_limiter = Limiter()
        self._provider_caps: dict[str, int] = {}
        for manifest in manifests.values():
            self._provider_caps[manifest.provider] = max(
                self._provider_caps.get(manifest.provider, 0), manifest.limits.max_concurrent
            )
        self.batches: dict[str, Batch] = {}
        self.jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._adapters: dict[str, ProviderAdapter] = {}
        self._remote: dict[str, tuple[ProviderAdapter, Any]] = {}  # job id -> (adapter, handle) once submitted
        self._clients: dict[int, CloseableClient] = {}
        self._leases: dict[int, int] = {}
        self._retired: set[int] = set()
        self._closing: set[int] = set()
        self._close_tasks: set[asyncio.Task[None]] = set()
        self._remote_tasks: set[asyncio.Task[None]] = set()
        self._input_tasks: set[asyncio.Task[dict[str, list[InputAsset]]]] = set()
        self._shutting_down = False
        self._shutdown_task: asyncio.Task[None] | None = None

    # ---------- public ----------
    def create_batch(self, jobs: list[Job], estimate: dict[str, Any], confirmed: bool, batch_id: str) -> Batch:
        self._ensure_running()
        batch = Batch(id=batch_id, jobs=jobs, estimate=estimate, confirmed=confirmed)
        self.batches[batch.id] = batch
        for j in jobs:
            self.jobs[j.id] = j
        self._refresh(batch)
        self.hub.publish("batch.updated", self.batch_summary(batch))
        for j in jobs:
            self._start(j)
        return batch

    def get_batch(self, batch_id: str) -> Batch:
        b = self.batches.get(batch_id)
        if b is None:
            raise ApiError("not_found", f"batch {batch_id} not found")
        self._refresh(b)
        return b

    def get_job(self, job_id: str) -> Job:
        j = self.jobs.get(job_id)
        if j is None:
            raise ApiError("not_found", f"job {job_id} not found")
        return j

    def cancel_batch(self, batch_id: str) -> Batch:
        b = self.get_batch(batch_id)
        for j in b.jobs:
            if j.status in TERMINAL:
                continue
            if j.status == "running":
                j.best_effort_cancel = True  # request already sent to the provider; cannot be recalled
                j.note = "canceled (best-effort: provider may still finish and bill)"
                self._remote_cancel(j)
            self._set(j, "canceled")
            t = self._tasks.get(j.id)
            if t and not t.done():
                t.cancel()
        self._refresh(b)
        return b

    def _remote_cancel(self, j: Job) -> None:
        """Adapters with a `cancel(handle)` (Seedance: only while the task is still queued) get a best-effort call."""
        ad, handle = self._remote.get(j.id, (None, None))
        cancel = getattr(ad, "cancel", None)
        if cancel is None:
            return
        if self._shutting_down:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.debug("remote cancel requires a running event loop")
            return
        lease = self._lease_client(self._adapter_client(ad))

        async def _go() -> None:
            try:
                await cancel(handle)
            except Exception:  # noqa: BLE001 - best effort: the job is already marked canceled
                log.debug("remote cancel failed", exc_info=True)

        task = loop.create_task(_go(), name=f"cancel-{j.id}")
        self._remote_tasks.add(task)

        def finished(completed: asyncio.Task[None]) -> None:
            self._remote_tasks.discard(completed)
            self._release_client(lease)

        task.add_done_callback(finished)

    def retry_job(self, job_id: str, confirm: bool = False) -> Job:
        self._ensure_running()
        old = self.get_job(job_id)
        if old.status not in ("failed", "blocked", "canceled"):
            raise ApiError("invalid", f"job is {old.status}; only failed/blocked/canceled jobs can be retried")
        s = self.settings()
        cap = int(s.get("maxJobsPerBatch", 24))
        b = self.batches[old.batch_id]
        # invariant 6 / 23: the batch cap counts outputs of the batch; the retried job replaces `old` (and any
        # job already superseded by an earlier retry), so retrying inside a full batch is fine but growing it is not
        superseded = {x.retry_of for x in b.jobs if x.retry_of} | {old.id}
        total = sum(x.variant_count for x in b.jobs if x.id not in superseded) + old.variant_count
        if total > cap:
            raise ApiError("invalid", f"retry would make the batch {total} outputs, over the limit of {cap}",
                           {"jobCount": total, "maxJobsPerBatch": cap})
        new = old.model_copy(deep=True)
        new.id = uuid.uuid4().hex
        new.status = "queued"
        new.error = None
        new.assets = []
        new.warnings = []
        new.retry_of = old.id
        new.operation_id = None
        new.attempts = 0
        new.note = f"manual retry of {old.id}"
        new.best_effort_cancel = False
        new.created_at = new.updated_at = now_iso()
        if self.prices is not None:  # a retry spends money again: same cost gate as a batch (invariants 6, 15, 23)
            lo, hi, _, unknown = estimate_job_ex(self.manifests[new.model_id], new, self.prices(),
                                                 int(s.get("staleDays", 30)))
            threshold = float(s.get("confirmThresholdUsd", 5))
            if (unknown or hi > threshold) and not confirm:
                raise ApiError(
                    "confirm_required",
                    ("price unknown for this retry" if unknown else f"retry costs up to ${hi:.2f} (> ${threshold:.2f})")
                    + "; resend with confirmOverThreshold=true",
                    {"minUsd": lo, "maxUsd": hi, "thresholdUsd": threshold, "unknownPrice": unknown},
                )
            new.cost_estimate_usd = [lo, hi]
        self.jobs[new.id] = new
        b.jobs.append(new)
        self._refresh(b)
        self.hub.publish("job.updated", self.job_event(new))
        self.hub.publish("batch.updated", self.batch_summary(b))
        self._start(new)
        return new

    async def shutdown(self) -> None:
        if self._shutdown_task is None:
            self._shutting_down = True
            self._shutdown_task = asyncio.create_task(self._shutdown(), name="jobs-shutdown")
        await asyncio.shield(self._shutdown_task)

    async def _shutdown(self) -> None:
        tasks = [*self._tasks.values(), *self._remote_tasks]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*list(self._input_tasks), return_exceptions=True)
        await self.close_adapters()

    async def close_adapters(self) -> None:
        """Close the httpx clients owned by cached adapters (shutdown)."""
        self.reset_adapters()
        for client in list(self._clients.values()):
            self.retire_client(client)
        while self._close_tasks:
            tasks = list(self._close_tasks)
            await asyncio.gather(*tasks, return_exceptions=True)
            self._close_tasks.difference_update(tasks)

    def reset_adapters(self, provider: str | None = None) -> None:
        """Drop cached adapters (provider reconfigured) and close their clients in the background."""
        for model_id, adapter in list(self._adapters.items()):
            if provider is not None and self.manifests[model_id].provider != provider:
                continue
            del self._adapters[model_id]
            client = self._adapter_client(adapter)
            if client is not None:
                self.retire_client(client)

    @staticmethod
    def _adapter_client(adapter: ProviderAdapter | None) -> CloseableClient | None:
        client = getattr(adapter, "client", None)
        return cast(CloseableClient, client) if callable(getattr(client, "aclose", None)) else None

    def _ensure_running(self) -> None:
        if self._shutting_down:
            raise ApiError("invalid", "job manager is shutting down")

    def _lease_client(self, client: CloseableClient | None) -> int | None:
        self._ensure_running()
        if client is None:
            return None
        identity = id(client)
        if identity in self._closing:
            raise ApiError("invalid", "adapter client is closing")
        self._clients[identity] = client
        self._leases[identity] = self._leases.get(identity, 0) + 1
        return identity

    def _release_client(self, identity: int | None) -> None:
        if identity is None:
            return
        remaining = self._leases[identity] - 1
        if remaining:
            self._leases[identity] = remaining
        else:
            del self._leases[identity]
            self._schedule_close(identity)

    def retire_client(self, client: CloseableClient) -> None:
        """Retain retired clients without a loop; close only after their last lease."""
        identity = id(client)
        self._clients[identity] = client
        self._retired.add(identity)
        self._schedule_close(identity)

    def _schedule_close(self, identity: int) -> None:
        if identity not in self._retired or identity in self._leases or identity in self._closing:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._closing.add(identity)
        task = loop.create_task(self._close_client(identity), name=f"client-close-{identity}")
        self._close_tasks.add(task)
        task.add_done_callback(self._close_tasks.discard)

    async def _close_client(self, identity: int) -> None:
        try:
            await self._clients[identity].aclose()
        except Exception:
            log.debug("adapter client close failed", exc_info=True)
        finally:
            self._clients.pop(identity, None)
            self._retired.discard(identity)
            self._closing.discard(identity)

    async def wait_batch(self, batch_id: str, timeout: float = 30.0) -> Batch:
        """Test/helper: wait until every job in the batch is terminal."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            b = self.get_batch(batch_id)
            if all(j.status in TERMINAL for j in b.jobs):
                return b
            await asyncio.sleep(0.02)
        raise TimeoutError(batch_id)

    # ---------- events / views ----------
    @staticmethod
    def job_event(j: Job) -> dict[str, Any]:
        return j.model_dump(by_alias=True, mode="json")

    @staticmethod
    def batch_summary(b: Batch) -> dict[str, Any]:
        return {"id": b.id, "status": b.status, "counts": b.counts, "confirmed": b.confirmed}

    def _refresh(self, b: Batch) -> None:
        counts: dict[str, int] = {}
        for j in b.jobs:
            counts[j.status] = counts.get(j.status, 0) + 1
        b.counts = counts
        active = counts.get("queued", 0) + counts.get("running", 0)
        b.status = "queued" if active == len(b.jobs) and counts.get("running", 0) == 0 else \
            ("running" if active else "completed")

    def _set(self, j: Job, status: str, error: AdapterError | None = None) -> None:
        if j.status in TERMINAL:
            return  # invariant 4: terminal states are final
        j.status = status  # type: ignore[assignment]
        if error is not None:
            j.error = JobError(kind=error.kind, message=error.message)
        j.updated_at = now_iso()
        b = self.batches.get(j.batch_id)
        if b:
            self._refresh(b)
        self.hub.publish("job.updated", self.job_event(j))
        if b:
            self.hub.publish("batch.updated", self.batch_summary(b))

    # ---------- runner ----------
    def _start(self, j: Job) -> None:
        self._ensure_running()
        task = asyncio.create_task(self._run(j), name=f"job-{j.id}")
        self._tasks[j.id] = task

        def finished(completed: asyncio.Task[None]) -> None:
            if self._tasks.get(j.id) is completed:
                self._tasks.pop(j.id, None)

        task.add_done_callback(finished)

    def _load_inputs(self, j: Job) -> dict[str, list[InputAsset]]:
        inputs: dict[str, list[InputAsset]] = {}
        try:
            for slot, val in j.assets_in.items():
                ids = val if isinstance(val, list) else [val]
                items: list[InputAsset] = []
                inputs[slot] = items
                for aid in ids:
                    asset = self.storage.get(aid)
                    items.append(InputAsset(id=aid, mime=asset.mime, data=self.storage.read_bytes(aid)))
            return inputs
        except Exception:
            for items in inputs.values():
                items.clear()
            inputs.clear()
            raise

    async def _inputs_for(self, j: Job) -> dict[str, list[InputAsset]]:
        task = asyncio.create_task(asyncio.to_thread(self._load_inputs, j), name=f"inputs-{j.id}")
        self._input_tasks.add(task)
        try:
            inputs = await asyncio.shield(task)
            if j.status in TERMINAL or self._shutting_down:
                inputs.clear()
                raise asyncio.CancelledError
            return inputs
        except asyncio.CancelledError:
            drain = asyncio.gather(task, return_exceptions=True)
            while not drain.done():
                try:
                    await asyncio.shield(drain)
                except asyncio.CancelledError:
                    continue
            result = drain.result()[0]
            if isinstance(result, dict):
                result.clear()
            elif isinstance(result, BaseException):
                log.debug("input loading failed during cancellation", exc_info=(type(result), result, result.__traceback__))
            raise
        finally:
            self._input_tasks.discard(task)

    def _adapter(self, m: ModelManifest) -> ProviderAdapter:
        if m.id not in self._adapters:
            self._adapters[m.id] = self.adapter_for(m)
        return self._adapters[m.id]

    async def _run(self, j: Job) -> None:
        m = self.manifests[j.model_id]
        try:
            while True:
                if j.status in TERMINAL:
                    return
                err: AdapterError | None = None
                try:
                    async with AsyncExitStack() as slots:
                        if m.limits.concurrency_group:
                            await slots.enter_async_context(self.model_limiter.slot(m.id, m.limits.max_concurrent))
                        await slots.enter_async_context(self.limiter.slot(
                            m.limits.concurrency_group or m.id, m.limits.max_concurrent, m.limits.rpm
                        ))
                        await slots.enter_async_context(self.provider_limiter.slot(
                            m.provider, self._provider_caps[m.provider]
                        ))
                        if j.status in TERMINAL:  # canceled while waiting for a slot
                            return
                        await self._attempt(j, m)
                        return
                except AdapterError as e:
                    err = e
                except ApiError as e:  # e.g. provider not configured -> auth
                    err = AdapterError(e.kind, e.message)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - never let a job task die silently
                    log.exception("job %s crashed", j.id)
                    err = AdapterError("invalid", f"internal error: {type(e).__name__}")

                # only reached for errors raised BEFORE a submit handle existed (see _attempt)
                s = self.settings()
                if err.kind == "blocked":
                    self._set(j, "blocked", err)
                    return
                if err.kind == "quota":
                    limit = int(s["maxAttempts"])
                elif err.kind == "network" and getattr(err, "before_send", False):
                    limit = min(2, int(s["maxAttempts"]))
                else:
                    limit = 0  # invalid/auth/timeout/network-after-send: resubmitting could bill twice
                if j.attempts >= limit:
                    self._set(j, "failed", err)
                    return
                delay = backoff_delay(j.attempts, s["retryBaseSeconds"], s["retryMaxSeconds"])
                j.note = f"{err.kind}: retrying in {delay:.1f}s (attempt {j.attempts}/{limit})"
                self._set(j, "running")
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self._set(j, "canceled")
        finally:
            self._remote.pop(j.id, None)

    def _fail_after_submit(self, j: Job, err: AdapterError) -> None:
        """Terminal failure once an operation exists: never resubmitted (invariant 14)."""
        msg = err.message + (f" (operation {j.operation_id})" if j.operation_id else "")
        self._set(j, "blocked" if err.kind == "blocked" else "failed", AdapterError(err.kind, msg))

    async def _transient(self, j: Job, what: str, call: Callable[[], Any], deadline: float | None = None) -> Any:
        """Run `call` retrying transient errors a bounded number of times on the SAME operation."""
        s = self.settings()
        limit = max(2, int(s["maxAttempts"]))
        n = 0
        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise AdapterError("timeout", "poll deadline exceeded")
            try:
                if remaining is None:
                    return await call()
                try:
                    result = await asyncio.wait_for(call(), timeout=remaining)
                except TimeoutError:
                    raise AdapterError("timeout", "poll deadline exceeded") from None
                if time.monotonic() >= deadline:
                    raise AdapterError("timeout", "poll deadline exceeded")
                return result
            except AdapterError as e:
                if deadline is not None and time.monotonic() >= deadline:
                    raise AdapterError("timeout", "poll deadline exceeded") from None
                if e.kind not in TRANSIENT or n >= limit:
                    raise
                n += 1
                delay = backoff_delay(n, s["retryBaseSeconds"], s["retryMaxSeconds"])
                if deadline is not None:
                    delay = min(delay, max(0.0, deadline - time.monotonic()))
                j.note = f"{what}: {e.kind}, retrying in {delay:.1f}s ({n}/{limit}); operation is not resubmitted"
                self._set(j, "running")
                await asyncio.sleep(delay)

    async def _attempt(self, j: Job, m: ModelManifest) -> None:
        adapter = self._adapter(m)
        lease = self._lease_client(self._adapter_client(adapter))
        try:
            await self._attempt_leased(j, m, adapter)
        finally:
            j.inputs = {}
            self._release_client(lease)

    async def _attempt_leased(self, j: Job, m: ModelManifest, adapter: ProviderAdapter) -> None:
        j.inputs = await self._inputs_for(j)
        j.attempts += 1
        j.note = None
        self._set(j, "running")
        try:
            adapter.build_payload(j)  # fail fast on payload errors
            handle = await adapter.submit(j)
        finally:
            j.inputs = {}  # free reference-image bytes as soon as the request left (reloaded if resubmitted)
        # ---- from here on an operation exists: never call submit again ----
        j.operation_id = handle.id if handle.id != j.id else None
        self._remote[j.id] = (adapter, handle)
        j.updated_at = now_iso()
        self.hub.publish("job.updated", self.job_event(j))
        try:
            await self._finish(j, m, adapter, handle)
        except AdapterError as e:
            self._fail_after_submit(j, e)
        except ApiError as e:
            self._fail_after_submit(j, AdapterError(e.kind, e.message))

    async def _finish(self, j: Job, m: ModelManifest, adapter: ProviderAdapter, handle: Any) -> None:
        s = self.settings()
        timeout = float(s.get("jobTimeoutSeconds", 900))
        started = time.monotonic()
        deadline = started + timeout
        while True:
            res = await self._transient(j, "poll", lambda: adapter.poll(handle), deadline)
            if res.state == "done":
                break
            if res.state == "failed":
                raise res.error or AdapterError("invalid", "job failed")
            if time.monotonic() >= deadline:
                raise AdapterError("timeout", f"no result after {timeout:.0f}s")
            interval = adapter.poll_interval_s
            if interval is None:
                interval = float(self.settings().get("pollIntervalSeconds", 10.0))
            await asyncio.sleep(min(interval * random.uniform(0.8, 1.2), max(0.0, deadline - time.monotonic())))
        files = await self._transient(j, "download", lambda: adapter.download(res.outputs, self.storage.run_dir))
        res.outputs.clear()
        if isinstance(getattr(handle, "data", None), dict):
            handle.data.clear()  # drop any bytes the adapter kept for the poll phase
        warnings = list(res.warnings)
        if len(files) < j.variant_count:
            warnings.append(f"received {len(files)} of {j.variant_count} requested outputs")
        elif len(files) > j.variant_count:
            warnings.append(f"received {len(files)} outputs for {j.variant_count} requested")
        sidecar_job = j.model_dump(by_alias=True, mode="json", exclude={"assets"})
        sidecar_job["status"] = "succeeded"
        sidecar_job["warnings"] = warnings
        assets = []
        for i, f in enumerate(files):
            a = await asyncio.to_thread(self.storage.register_file, f.path, f.mime, "output",
                                        {"jobId": j.id, "index": i}, f.sha256, f.size_bytes)
            self.storage.set_sidecar(a.id, {"job": sidecar_job, "outputIndex": i})
            assets.append(a)
        j.assets = assets
        j.warnings = warnings
        j.note = None
        self._set(j, "succeeded")
