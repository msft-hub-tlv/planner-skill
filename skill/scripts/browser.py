"""browser.py — Playwright UI automation for Planner Premium writes.

Project for the Web blocks direct Dataverse writes via plugin
("You cannot directly do 'Update'/'Create' operation to 'msdyn_projecttask'").
The web UI at planner.cloud.microsoft uses a privileged service-principal proxy
that bypasses those checks — so for writes we drive the UI.

Auth: persistent Edge user-data-dir at ~/.copilot/m-skills/planner/profile.
Seed it once with `planner browser-login` (visible browser); subsequent calls
run headless.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

PROFILE_DIR = Path(
    os.environ.get(
        "PLANNER_PROFILE_DIR",
        str(Path.home() / ".copilot/m-skills/planner/profile"),
    )
)
SCREENSHOT_DIR = Path.home() / ".copilot/m-skills/planner/.cache/screenshots"
DEFAULT_TIMEOUT_MS = 45_000


def _shot(page, name: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{int(time.time())}-{name}.png"
    try:
        # sync helper used inside async context — schedule but don't await
        asyncio.get_event_loop().create_task(page.screenshot(path=str(path)))
    except Exception:
        pass
    return str(path)


async def _shot_async(page, name: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{int(time.time())}-{name}.png"
    try:
        await page.screenshot(path=str(path))
    except Exception:
        pass
    return str(path)


class BrowserPlanner:
    """Async context-manager wrapping a persistent Edge session on planner.cloud.microsoft."""

    def __init__(self, headless: bool = True, slow_mo_ms: int = 0):
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms
        self._pw = None
        self._ctx = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            channel="msedge",
            user_data_dir=str(PROFILE_DIR),
            headless=self.headless,
            slow_mo=self.slow_mo_ms,
            viewport={"width": 1500, "height": 950},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._ctx.set_default_timeout(DEFAULT_TIMEOUT_MS)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if self._ctx:
                await self._ctx.close()
        finally:
            if self._pw:
                await self._pw.stop()

    # ── public ops ────────────────────────────────────────────────────

    async def login(self, start_url: str = "https://planner.cloud.microsoft/") -> None:
        """Open Planner and let the user sign in. Use with headless=False."""
        page = await self._ctx.new_page()
        await page.goto(start_url, wait_until="domcontentloaded")
        print(
            "Browser opened — sign in with the Microsoft account that owns the plan, "
            "then close the window when you see the Planner UI.",
            flush=True,
        )
        # wait for either close or hitting the planner shell
        deadline = time.time() + 600
        while time.time() < deadline:
            if page.is_closed():
                break
            try:
                title = await page.title()
                if "planner" in (title or "").lower():
                    # give the user a moment to confirm tenant picker etc
                    await asyncio.sleep(3)
                    if not page.is_closed():
                        # don't auto-close: let the user verify and shut it themselves
                        pass
            except Exception:
                pass
            await asyncio.sleep(1)

    async def _open_plan(self, plan_url: str):
        page = await self._ctx.new_page()
        await page.goto(plan_url, wait_until="domcontentloaded")
        # Planner shell loads heavy JS. Wait for the actual Add-task control
        # (or any task row) — the empty role=grid skeleton appears earlier.
        long_timeout = max(DEFAULT_TIMEOUT_MS, 90_000)
        candidates = [
            "button:has-text('Add new task')",
            "button:has-text('Add task')",
            "button:has-text('New task')",
            "button:has-text('הוספת משימה')",
            "[role='textbox'][aria-label*='Add new task' i]",
            "[role='textbox'][aria-label*='task name' i]",
            "[role='gridcell']",
            "[role='row'][aria-rowindex]",
        ]
        try:
            await page.wait_for_selector(", ".join(candidates), timeout=long_timeout)
        except Exception:
            shot = await _shot_async(page, "open-plan-timeout")
            raise RuntimeError(
                f"Timed out waiting for Planner grid to load. Screenshot: {shot}. "
                "If the page asked you to sign in, run `planner browser-login` first."
            )
        # Give the grid an extra moment to fully hydrate
        await page.wait_for_timeout(1500)
        return page

    async def create_task(
        self,
        plan_url: str,
        name: str,
        bucket_name: Optional[str] = None,
        description: Optional[str] = None,
        labels: Optional[list] = None,
        _page=None,
    ) -> dict:
        own_page = _page is None
        page = _page or await self._open_plan(plan_url)
        try:
            # Switch to Grid view if we landed on Board — Grid is most reliable
            try:
                grid_btn = page.get_by_role("tab", name="Grid", exact=False)
                if await grid_btn.count() > 0:
                    await grid_btn.first.click()
                    await page.wait_for_timeout(800)
            except Exception:
                pass

            # Click "Add new task" / equivalent
            add_btn = None
            for label in ("Add new task", "Add task", "New task", "הוספת משימה"):
                loc = page.get_by_role("button", name=label, exact=False)
                if await loc.count() > 0:
                    add_btn = loc.first
                    break
            if add_btn is None:
                inp = page.get_by_role("textbox", name="Add new task", exact=False)
                if await inp.count() > 0:
                    await inp.first.click()
                    await inp.first.fill(name)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1500)
                else:
                    shot = await _shot_async(page, "no-add-button")
                    raise RuntimeError(f"Could not find an Add-task control. Screenshot: {shot}")
            else:
                await add_btn.click()
                await page.keyboard.type(name, delay=10)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1500)

            # Move to bucket via right-click (only meaningful when there's >1 bucket;
            # for the Backlog default this is a no-op fallback)
            if bucket_name:
                try:
                    row = page.get_by_role("row", name=name, exact=False).first
                    await row.click(button="right")
                    move = page.get_by_role("menuitem", name="Move to", exact=False)
                    if await move.count() > 0:
                        await move.first.click()
                        choice = page.get_by_role("menuitem", name=bucket_name, exact=False)
                        if await choice.count() > 0:
                            await choice.first.click()
                            await page.wait_for_timeout(500)
                    # dismiss any open menu
                    await page.keyboard.press("Escape")
                except Exception:
                    pass

            applied: dict = {"name": name, "bucket": bucket_name}

            if description or labels:
                await self._fill_details(page, name, description=description, labels=labels)
                if description:
                    applied["description"] = True
                if labels:
                    applied["labels"] = labels

            return {"ok": True, **applied}
        finally:
            if own_page:
                await page.close()

    async def _open_detail_panel(self, page, task_name: str):
        """Focus the task-name gridcell for `task_name` and press Alt+I."""
        cell = page.locator(
            f"div[role='row']:has-text({task_name!r}) "
            f"[role='gridcell'][aria-label*='Task Name']"
        ).first
        await cell.wait_for(timeout=15000)
        await cell.click()
        await page.wait_for_timeout(200)
        await page.keyboard.press("Alt+i")
        # Wait for panel region
        await page.locator(
            f"[role='region'][aria-label*='Task details for {task_name}']"
        ).first.wait_for(timeout=15000)
        await page.wait_for_timeout(400)

    async def _fill_details(
        self,
        page,
        task_name: str,
        *,
        description: Optional[str] = None,
        labels: Optional[list] = None,
    ) -> None:
        await self._open_detail_panel(page, task_name)
        try:
            if description:
                # contenteditable div: aria-label "Add a note..."
                note = page.locator(
                    "[role='textbox'][aria-label*='Add a note'], "
                    "[contenteditable='true'][aria-label*='Add a note']"
                ).first
                try:
                    await note.wait_for(timeout=10000)
                except Exception:
                    shot = await _shot_async(page, f"no-notes-{task_name[:20]}")
                    raise RuntimeError(
                        f"Could not find Notes field for {task_name!r}. Screenshot: {shot}"
                    )
                await note.click()
                await page.keyboard.type(description, delay=2)

            if labels:
                combo = page.locator(
                    "[role='combobox'][aria-label*='label to apply'], "
                    "input[aria-label*='Search for label']"
                ).first
                for lab in labels:
                    lab = lab.strip()
                    if not lab:
                        continue
                    await combo.click()
                    await combo.fill("")
                    await page.keyboard.type(lab, delay=15)
                    await page.wait_for_timeout(600)
                    # Try to pick a matching suggestion (existing label) first
                    picked = False
                    for opt_role in ("option", "menuitem"):
                        opt = page.get_by_role(opt_role, name=lab, exact=False).first
                        try:
                            if await opt.count() > 0:
                                await opt.click(timeout=2000)
                                picked = True
                                break
                        except Exception:
                            pass
                    if not picked:
                        # Create new label by pressing Enter
                        await page.keyboard.press("Enter")
                    await page.wait_for_timeout(400)
        finally:
            close = page.get_by_role("button", name="Close pane", exact=False)
            try:
                if await close.count() > 0:
                    await close.first.click()
                    await page.wait_for_timeout(300)
            except Exception:
                pass

    async def bulk_create(self, plan_url: str, items: list) -> list:
        """items: list of dicts with name, bucket_name?, description?, labels?"""
        page = await self._open_plan(plan_url)
        results = []
        try:
            for it in items:
                try:
                    res = await self.create_task(
                        plan_url,
                        name=it["name"],
                        bucket_name=it.get("bucket_name"),
                        description=it.get("description"),
                        labels=it.get("labels"),
                        _page=page,
                    )
                    results.append(res)
                except Exception as e:
                    shot = await _shot_async(page, f"bulk-fail-{len(results)}")
                    results.append({"ok": False, "name": it.get("name"),
                                    "error": str(e), "screenshot": shot})
                    # Try to close any stuck panel
                    try:
                        await page.keyboard.press("Escape")
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
            return results
        finally:
            await page.close()

    async def _open_task_panel(self, page, task_identifier: str):
        """Click the task in the grid to open its details panel."""
        # try by accessible name (subject)
        candidate = page.get_by_role("row", name=task_identifier, exact=False)
        if await candidate.count() == 0:
            candidate = page.get_by_text(task_identifier, exact=False).first
        if await candidate.count() == 0:
            shot = await _shot_async(page, "task-not-found")
            raise RuntimeError(
                f"Could not find task matching {task_identifier!r}. Screenshot: {shot}"
            )
        await candidate.first.click()
        # the side panel takes a moment to slide in
        await page.wait_for_timeout(1200)

    async def complete_task(self, plan_url: str, task_identifier: str) -> dict:
        page = await self._open_plan(plan_url)
        try:
            await self._open_task_panel(page, task_identifier)
            # Look for a Mark complete button or a checkbox
            for label in ("Mark task complete", "Mark complete", "Complete", "סמן כהושלם"):
                btn = page.get_by_role("button", name=label, exact=False)
                if await btn.count() > 0:
                    await btn.first.click()
                    await page.wait_for_timeout(800)
                    return {"ok": True, "task": task_identifier, "completed": True}
            # checkbox fallback
            cb = page.get_by_role("checkbox", name="Complete", exact=False)
            if await cb.count() > 0:
                await cb.first.check()
                await page.wait_for_timeout(800)
                return {"ok": True, "task": task_identifier, "completed": True}
            shot = await _shot_async(page, "no-complete-control")
            raise RuntimeError(f"Could not find a Complete control. Screenshot: {shot}")
        finally:
            await page.close()

    async def update_task(
        self,
        plan_url: str,
        task_identifier: str,
        *,
        name: Optional[str] = None,
        percent: Optional[int] = None,
        start: Optional[str] = None,
        due: Optional[str] = None,
    ) -> dict:
        page = await self._open_plan(plan_url)
        applied: dict = {}
        try:
            await self._open_task_panel(page, task_identifier)

            if name is not None:
                tb = page.get_by_role("textbox", name="Task name", exact=False)
                if await tb.count() == 0:
                    tb = page.get_by_role("textbox", name="Name", exact=False)
                if await tb.count() > 0:
                    await tb.first.click()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Delete")
                    await tb.first.fill(name)
                    await page.keyboard.press("Tab")
                    applied["name"] = name

            if percent is not None:
                # Progress dropdown: Not started / In progress / Completed
                # Most exact-percent control is a number spinner labelled "% complete"
                spin = page.get_by_role("spinbutton", name="% complete", exact=False)
                if await spin.count() > 0:
                    await spin.first.fill(str(int(percent)))
                    await page.keyboard.press("Tab")
                    applied["percent"] = percent
                else:
                    # Fall back to status combo
                    combo = page.get_by_role("combobox", name="Progress", exact=False)
                    if await combo.count() > 0:
                        target = "Completed" if percent >= 100 else ("In progress" if percent > 0 else "Not started")
                        await combo.first.click()
                        opt = page.get_by_role("option", name=target, exact=False)
                        if await opt.count() > 0:
                            await opt.first.click()
                            applied["percent"] = percent

            for field_label, value, key in (("Start date", start, "start"), ("Due date", due, "due")):
                if value is None:
                    continue
                tb = page.get_by_role("textbox", name=field_label, exact=False)
                if await tb.count() > 0:
                    await tb.first.click()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Delete")
                    await tb.first.fill(value)
                    await page.keyboard.press("Tab")
                    applied[key] = value

            await page.wait_for_timeout(600)
            return {"ok": True, "task": task_identifier, "applied": applied}
        finally:
            await page.close()
