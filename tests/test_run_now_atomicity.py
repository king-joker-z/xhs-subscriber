"""Regression tests for atomic acceptance of POST /run background work."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import Response

from src import api
from src.scheduler import XHSScheduler


class RunNowAtomicityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.previous_scheduler = api._scheduler

    def tearDown(self) -> None:
        api._scheduler = self.previous_scheduler

    @staticmethod
    def _scheduler(run_once: object) -> XHSScheduler:
        scheduler = XHSScheduler.__new__(XHSScheduler)
        scheduler._run_once_active = False
        scheduler.run_once = run_once  # type: ignore[method-assign]
        return scheduler

    @staticmethod
    async def _wait_until_released(scheduler: XHSScheduler) -> None:
        for _ in range(20):
            if not scheduler._run_once_active:
                return
            await asyncio.sleep(0)
        raise AssertionError("run-once slot was not released")

    async def test_concurrent_run_requests_accept_once_and_release_after_completion(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        executions = 0

        async def run_once(*, _reserved: bool = False) -> None:
            nonlocal executions
            self.assertTrue(_reserved)
            executions += 1
            started.set()
            await release.wait()

        api._scheduler = self._scheduler(run_once)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://testserver"
        ) as client:
            responses = await asyncio.gather(*(client.post("/run") for _ in range(4)))

        self.assertEqual([response.status_code for response in responses].count(202), 1)
        self.assertEqual([response.status_code for response in responses].count(409), 3)
        self.assertEqual([response.json()["status"] for response in responses].count("accepted"), 1)
        self.assertEqual([response.json()["status"] for response in responses].count("already_running"), 3)
        await started.wait()
        self.assertEqual(executions, 1)

        release.set()
        await self._wait_until_released(api._scheduler)

    async def test_exception_releases_slot_for_the_next_request(self) -> None:
        executions = 0

        async def run_once(*, _reserved: bool = False) -> None:
            nonlocal executions
            executions += 1
            raise RuntimeError("test failure")

        api._scheduler = self._scheduler(run_once)

        self.assertEqual((await api.run_now(Response())).status, "accepted")
        await self._wait_until_released(api._scheduler)
        self.assertEqual((await api.run_now(Response())).status, "accepted")
        await self._wait_until_released(api._scheduler)
        self.assertEqual(executions, 2)

    async def test_cancel_before_run_once_starts_releases_slot_and_allows_retry(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def run_once(*, _reserved: bool = False) -> None:
            started.set()
            await release.wait()

        scheduler = self._scheduler(run_once)
        original_create_task = asyncio.get_running_loop().create_task
        captured_task: asyncio.Task[object] | None = None

        def create_and_cancel(coro: object) -> asyncio.Task[object]:
            nonlocal captured_task
            captured_task = original_create_task(coro)  # type: ignore[arg-type]
            captured_task.cancel()
            return captured_task

        with patch.object(asyncio.get_running_loop(), "create_task", side_effect=create_and_cancel):
            self.assertTrue(scheduler.try_trigger_now())

        self.assertIsNotNone(captured_task)
        await self._wait_until_released(scheduler)
        self.assertFalse(started.is_set())
        self.assertTrue(scheduler.try_trigger_now())
        await started.wait()
        release.set()
        await self._wait_until_released(scheduler)

    async def test_create_task_failure_rolls_back_slot_and_run_endpoint_returns_503(self) -> None:
        async def run_once(*, _reserved: bool = False) -> None:
            raise AssertionError("must not run")

        scheduler = self._scheduler(run_once)
        api._scheduler = scheduler
        loop = asyncio.get_running_loop()
        with patch.object(loop, "create_task", side_effect=RuntimeError("loop unavailable")):
            with self.assertRaisesRegex(RuntimeError, "loop unavailable"):
                scheduler.try_trigger_now()
            self.assertFalse(scheduler._run_once_active)

            response = Response()
            result = await api.run_now(response)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(result.status, "scheduler_not_ready")
        self.assertFalse(scheduler._run_once_active)

    async def test_ordinary_run_once_and_api_reservation_exclude_each_other(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        executions = 0
        scheduler = XHSScheduler.__new__(XHSScheduler)
        scheduler._run_once_active = False
        scheduler._config = SimpleNamespace(subscriptions=[SimpleNamespace(enabled=True)])
        scheduler._save_state = lambda: None  # type: ignore[method-assign]

        async def process_subscription(_: object) -> None:
            nonlocal executions
            executions += 1
            started.set()
            await release.wait()

        scheduler._process_subscription = process_subscription  # type: ignore[method-assign]
        api._scheduler = scheduler

        ordinary_task = asyncio.create_task(scheduler.run_once())
        await started.wait()
        self.assertFalse(scheduler.try_trigger_now())
        api_response = Response()
        self.assertEqual((await api.run_now(api_response)).status, "already_running")
        self.assertEqual(api_response.status_code, 409)

        release.set()
        await ordinary_task
        self.assertEqual(executions, 1)

        started.clear()
        release.clear()
        self.assertTrue(scheduler.try_trigger_now())
        await started.wait()
        await scheduler.run_once()
        self.assertEqual(executions, 2)
        self.assertTrue(scheduler._run_once_active)

        release.set()
        await self._wait_until_released(scheduler)

    async def test_run_endpoint_returns_503_without_scheduler(self) -> None:
        api._scheduler = None
        response = Response()
        result = await api.run_now(response)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(result.status, "scheduler_not_ready")


if __name__ == "__main__":
    unittest.main()
