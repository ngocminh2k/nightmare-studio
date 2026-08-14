from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .domain import EpisodeStatus, approved_status, can_transition


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StudioRepository:
    """SQLite persistence with explicit workflow and review records."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    brand_bible TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    source_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    script_draft TEXT NOT NULL DEFAULT '',
                    script_final TEXT NOT NULL DEFAULT '',
                    storyboard_json TEXT NOT NULL DEFAULT '[]',
                    cost_total REAL NOT NULL DEFAULT 0,
                    output_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                    gate TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS episode_events (
                    id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    scene_number INTEGER,
                    label TEXT NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    prompt TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS providers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None

    def create_project(self, name: str, description: str, brand_bible: str = "") -> dict[str, Any]:
        now, project_id = utc_now(), str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO projects(id, name, description, brand_bible, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, name.strip(), description.strip(), brand_bible.strip(), now, now),
            )
        return self.get_project(project_id)  # type: ignore[return-value]

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT p.*, COUNT(e.id) AS episode_count
                   FROM projects p LEFT JOIN episodes e ON e.project_id = p.id
                   GROUP BY p.id ORDER BY p.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return self._row(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())

    def find_project_by_name(self, name: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return self._row(conn.execute("SELECT * FROM projects WHERE name = ? ORDER BY created_at LIMIT 1", (name.strip(),)).fetchone())

    def update_project(self, project_id: str, **changes: str) -> dict[str, Any] | None:
        allowed = {key: value.strip() for key, value in changes.items() if key in {"name", "description", "brand_bible"} and value is not None}
        if not allowed:
            return self.get_project(project_id)
        columns = ", ".join(f"{key} = ?" for key in allowed)
        with self._connection() as conn:
            conn.execute(f"UPDATE projects SET {columns}, updated_at = ? WHERE id = ?", (*allowed.values(), utc_now(), project_id))
        return self.get_project(project_id)

    def create_episode(self, project_id: str, title: str, source_url: str, source_text: str) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise ValueError("Project does not exist")
        now, episode_id = utc_now(), str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO episodes(id, project_id, title, source_url, source_text, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (episode_id, project_id, title.strip(), source_url.strip(), source_text.strip(), EpisodeStatus.DISCOVERED.value, now, now),
            )
        return self.get_episode(episode_id)  # type: ignore[return-value]

    def list_episodes(self, project_id: str | None = None) -> list[dict[str, Any]]:
        query, params = "SELECT * FROM episodes", []
        if project_id:
            query += " WHERE project_id = ?"
            params.append(project_id)
        query += " ORDER BY updated_at DESC"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._episode_row(row) for row in rows]

    def source_urls(self) -> set[str]:
        with self._connection() as conn:
            rows = conn.execute("SELECT source_url FROM episodes WHERE source_url <> ''").fetchall()
        return {str(row["source_url"]) for row in rows}

    def _episode_row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        item = self._row(row)
        if not item:
            return None
        item["storyboard"] = json.loads(item.pop("storyboard_json") or "[]")
        return item

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return self._episode_row(conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone())

    def get_project_episode(self, project_id: str, episode_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            return self._episode_row(conn.execute("SELECT * FROM episodes WHERE id = ? AND project_id = ?", (episode_id, project_id)).fetchone())

    def update_episode(self, episode_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed_keys = {"title", "source_url", "source_text", "script_draft", "script_final", "cost_total", "output_path"}
        allowed = {key: value for key, value in changes.items() if key in allowed_keys}
        if "storyboard" in changes:
            allowed["storyboard_json"] = json.dumps(changes["storyboard"], ensure_ascii=False)
        if not allowed:
            return self.get_episode(episode_id)
        columns = ", ".join(f"{key} = ?" for key in allowed)
        with self._connection() as conn:
            conn.execute(f"UPDATE episodes SET {columns}, updated_at = ? WHERE id = ?", (*allowed.values(), utc_now(), episode_id))
        return self.get_episode(episode_id)

    def transition_episode(self, episode_id: str, target: EpisodeStatus | str, note: str = "") -> dict[str, Any]:
        episode = self.get_episode(episode_id)
        if not episode:
            raise ValueError("Episode does not exist")
        target_status = EpisodeStatus(target)
        if not can_transition(episode["status"], target_status):
            raise ValueError(f"Cannot transition from {episode['status']} to {target_status.value}")
        with self._connection() as conn:
            conn.execute("UPDATE episodes SET status = ?, updated_at = ? WHERE id = ?", (target_status.value, utc_now(), episode_id))
        if note:
            self.add_activity(episode_id, "workflow", note)
        return self.get_episode(episode_id)  # type: ignore[return-value]

    def add_review(self, episode_id: str, gate: str, decision: str, note: str = "") -> dict[str, Any]:
        if decision not in {"approved", "changes_requested"}:
            raise ValueError("Review decision must be approved or changes_requested")
        review_id = str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO reviews(id, episode_id, gate, decision, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (review_id, episode_id, gate, decision, note, utc_now()),
            )
        episode = self.get_episode(episode_id)
        if episode and decision == "approved":
            expected = {"script": EpisodeStatus.AWAITING_SCRIPT_REVIEW, "assets": EpisodeStatus.AWAITING_ASSET_REVIEW, "final": EpisodeStatus.AWAITING_FINAL_REVIEW}.get(gate)
            if expected and episode["status"] == expected.value:
                self.transition_episode(episode_id, approved_status(gate), note=f"{gate.title()} review approved")
        with self._connection() as conn:
            return self._row(conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone())  # type: ignore[return-value]

    def list_reviews(self, episode_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM reviews WHERE episode_id = ? ORDER BY created_at DESC", (episode_id,)).fetchall()
        return [dict(row) for row in rows]

    def create_job(self, episode_id: str, kind: str) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO jobs(id, episode_id, kind, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
                (job_id, episode_id, kind, utc_now()),
            )
        self.add_job_event(job_id, "info", f"Queued {kind} job")
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            job = self._row(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
        if job:
            job["result"] = json.loads(job.pop("result_json") or "{}")
        return job

    def list_jobs(self, episode_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE episode_id = ? ORDER BY created_at DESC", (episode_id,)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json") or "{}")
            items.append(item)
        return items

    def update_job(self, job_id: str, *, status: str | None = None, progress: int | None = None, error: str | None = None, result: dict[str, Any] | None = None) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if status is not None:
            fields["status"] = status
            if status == "running":
                fields["started_at"] = utc_now()
            if status in {"completed", "failed", "cancelled"}:
                fields["finished_at"] = utc_now()
        if progress is not None:
            fields["progress"] = max(0, min(100, progress))
        if error is not None:
            fields["error"] = error
        if result is not None:
            fields["result_json"] = json.dumps(result, ensure_ascii=False)
        if not fields:
            return self.get_job(job_id)  # type: ignore[return-value]
        columns = ", ".join(f"{key} = ?" for key in fields)
        with self._connection() as conn:
            conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", (*fields.values(), job_id))
        return self.get_job(job_id)  # type: ignore[return-value]

    def add_job_event(self, job_id: str, level: str, message: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO job_events(id, job_id, level, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), job_id, level, message, utc_now()),
            )

    def list_job_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM job_events WHERE job_id = ? ORDER BY created_at", (job_id,)).fetchall()
        return [dict(row) for row in rows]

    def add_activity(self, episode_id: str, level: str, message: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO episode_events(id, episode_id, level, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), episode_id, level, message, utc_now()),
            )

    def list_activity(self, episode_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM episode_events WHERE episode_id = ? ORDER BY created_at DESC", (episode_id,)).fetchall()
        return [dict(row) for row in rows]

    def dashboard(self) -> dict[str, Any]:
        episodes = self.list_episodes()
        status_counts: dict[str, int] = {}
        for episode in episodes:
            status_counts[episode["status"]] = status_counts.get(episode["status"], 0) + 1
        return {
            "project_count": len(self.list_projects()),
            "episode_count": len(episodes),
            "cost_total": round(sum(float(episode["cost_total"]) for episode in episodes), 2),
            "status_counts": status_counts,
            "recent_episodes": episodes[:8],
        }

    def episode_manifest(self, episode_id: str) -> dict[str, Any] | None:
        """Build a portable, secret-free record of an episode and its provenance."""

        episode = self.get_episode(episode_id)
        if not episode:
            return None
        return {
            "generated_at": utc_now(),
            "project": self.get_project(episode["project_id"]),
            "episode": episode,
            "reviews": self.list_reviews(episode_id),
            "jobs": self.list_jobs(episode_id),
            "activity": self.list_activity(episode_id),
        }
