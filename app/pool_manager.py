"""
pool_manager.py — Flowkit multi-account pool manager

Each account = one flowkit instance (python -m agent.main) running on its own port.
Pool manager polls /api/flow/credits on each, auto-switches when credit < threshold.

Config via env vars:
  FLOW_ACCOUNTS=8001:proj-uuid-1,8002:proj-uuid-2,...
  (port:project_id pairs, comma-separated)

  Or fallback: FLOW_ACCOUNTS=8001,8002,8003  (no project ids — flowkit uses its own session project)

Run: python -m uvicorn app.pool_manager:app --host 127.0.0.1 --port 8888
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.request import Request, urlopen
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

LOW_CREDIT_THRESHOLD = int(os.getenv("FLOW_LOW_CREDIT_THRESHOLD", "10"))
POLL_INTERVAL = int(os.getenv("FLOW_POLL_INTERVAL", "30"))


def _parse_accounts() -> list[dict]:
    """Parse FLOW_ACCOUNTS env var.

    Format: port:project_id,port:project_id,...
    Example: FLOW_ACCOUNTS=8100:abc-123,8101:def-456,8102:ghi-789
    """
    raw = os.getenv("FLOW_ACCOUNTS", "8100").strip()
    result = []
    for i, entry in enumerate(raw.split(",")):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            port_str, project_id = entry.split(":", 1)
        else:
            port_str, project_id = entry, ""
        result.append(
            {
                "id": f"acct-{i + 1:02d}",
                "port": int(port_str.strip()),
                "project_id": project_id.strip(),
            }
        )
    return result or [{"id": "acct-01", "port": 8100, "project_id": ""}]


ACCOUNTS_CFG = _parse_accounts()


@dataclass
class AccountState:
    id: str
    port: int
    project_id: str
    status: str = "offline"  # offline | ready | active | low | depleted
    credits: Optional[int] = None
    connected: bool = False
    jobs_done: int = 0
    jobs_failed: int = 0
    last_log: str = "initializing..."
    last_seen: float = 0.0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


pool: list[AccountState] = [AccountState(**a) for a in ACCOUNTS_CFG]
switch_log: list[dict] = []
total_jobs: int = 0
_lock = asyncio.Lock()


def active_account() -> Optional[AccountState]:
    return next((a for a in pool if a.status == "active"), None)


def next_ready() -> Optional[AccountState]:
    return next((a for a in pool if a.status == "ready"), None)


def _fetch_json(url: str, timeout: float = 5.0) -> Optional[dict]:
    try:
        with urlopen(Request(url), timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


async def poll_account(acct: AccountState) -> None:
    """Check flowkit health + credits for one account."""
    loop = asyncio.get_event_loop()

    # health check
    health = await loop.run_in_executor(None, _fetch_json, f"{acct.base_url}/health")
    if health is None:
        acct.connected = False
        if acct.status != "active":
            acct.status = "offline"
        acct.last_log = "flowkit unreachable"
        return

    acct.connected = health.get("extension_connected", False)
    if not acct.connected:
        if acct.status != "active":
            acct.status = "offline"
        acct.last_log = "extension not connected"
        acct.last_seen = time.time()
        return

    # credits
    cred_data = await loop.run_in_executor(None, _fetch_json, f"{acct.base_url}/api/flow/credits")
    now = time.time()
    acct.last_seen = now

    if cred_data is None:
        acct.last_log = "credits endpoint failed"
        return

    # flowkit /api/flow/credits returns tier info, not a numeric count
    # Try numeric keys first (future-proofing), fall back to tier mapping
    credits_num = cred_data.get("credits") or cred_data.get("remaining") or cred_data.get("balance")
    tier = cred_data.get("userPaygateTier") or cred_data.get("tier") or ""

    if isinstance(credits_num, (int, float)):
        acct.credits = int(credits_num)
        tier_status = None  # use numeric logic below
    elif tier:
        # Map tier string → synthetic credit value for status logic
        # TIER_TWO / TIER_ONE = paid tiers = healthy; TIER_ZERO / FREE = low; unknown = assume ok
        tier_upper = tier.upper()
        if "TIER_TWO" in tier_upper or "TIER_ONE" in tier_upper:
            acct.credits = 999  # synthetic: healthy
        elif "TIER_ZERO" in tier_upper or "FREE" in tier_upper:
            acct.credits = 5  # synthetic: low
        else:
            acct.credits = 100  # unknown tier, assume ok
        tier_status = tier
    else:
        acct.last_log = f"unknown credits format: {str(cred_data)[:60]}"
        return

    # classify
    if acct.status != "active":
        c = acct.credits
        if c == 0:
            acct.status = "depleted"
        elif c < LOW_CREDIT_THRESHOLD:
            acct.status = "low"
        else:
            acct.status = "ready"

    label = tier_status if tier_status else str(acct.credits)
    acct.last_log = f"credits={label}"


async def check_and_switch() -> None:
    global switch_log
    async with _lock:
        cur = active_account()

        # boot: pick first ready
        if cur is None:
            nxt = next_ready()
            if nxt:
                nxt.status = "active"
            return

        if cur.credits is not None and cur.credits < LOW_CREDIT_THRESHOLD:
            nxt = next_ready()
            if nxt:
                old = "depleted" if cur.credits == 0 else "low"
                cur.status = old
                nxt.status = "active"
                entry = {
                    "ts": time.strftime("%H:%M:%S"),
                    "from": cur.id,
                    "from_port": cur.port,
                    "from_credits": cur.credits,
                    "to": nxt.id,
                    "to_port": nxt.port,
                    "reason": f"credit {cur.credits} < {LOW_CREDIT_THRESHOLD}",
                }
                switch_log = ([entry] + switch_log)[:50]
                nxt.last_log = f"auto-switched from {cur.id}"
                cur.last_log = f"switched out — {cur.credits} credits left"


async def poll_loop() -> None:
    while True:
        await asyncio.gather(*[poll_account(a) for a in pool], return_exceptions=True)
        await check_and_switch()
        await asyncio.sleep(POLL_INTERVAL)


# ── FastAPI ──────────────────────────────────────────────────────────────────
app = FastAPI(title="Flow Pool Manager")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    asyncio.create_task(poll_loop())


@app.get("/api/pool-status")
async def pool_status():
    cur = active_account()
    return {
        "totalJobs": total_jobs,
        "activeId": cur.id if cur else None,
        "activePort": cur.port if cur else None,
        "activeProjectId": cur.project_id if cur else None,
        "switchLog": switch_log[:10],
        "accounts": [
            {
                "id": a.id,
                "port": a.port,
                "project_id": a.project_id,
                "base_url": a.base_url,
                "status": a.status,
                "credits": a.credits,
                "connected": a.connected,
                "jobsDone": a.jobs_done,
                "jobsFailed": a.jobs_failed,
                "lastLog": a.last_log,
                "lastSeen": int(a.last_seen) if a.last_seen else None,
            }
            for a in pool
        ],
    }


@app.get("/api/active")
async def get_active():
    """Return active account's flowkit URL — nightmare studio calls this to route jobs."""
    cur = active_account()
    if not cur:
        return {"error": "no active account", "url": None, "project_id": None}
    return {"url": cur.base_url, "project_id": cur.project_id, "id": cur.id, "credits": cur.credits}


@app.post("/api/switch")
async def manual_switch(target_id: str):
    async with _lock:
        cur = active_account()
        nxt = next((a for a in pool if a.id == target_id), None)
        if not nxt:
            return {"error": f"{target_id} not found"}
        if cur and cur is not nxt:
            cur.status = "ready" if (cur.credits or 0) >= LOW_CREDIT_THRESHOLD else "low"
        nxt.status = "active"
        switch_log.insert(
            0,
            {
                "ts": time.strftime("%H:%M:%S"),
                "from": cur.id if cur else None,
                "to": nxt.id,
                "reason": "manual",
            },
        )
        return {"ok": True, "active": target_id}


@app.post("/api/job-done")
async def job_done(account_id: str, failed: bool = False):
    global total_jobs
    a = next((x for x in pool if x.id == account_id), None)
    if a:
        if failed:
            a.jobs_failed += 1
        else:
            a.jobs_done += 1
            total_jobs += 1
    return {"ok": True}
