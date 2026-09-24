"""Configuration loading for the RunningHub workflow task pool.

Resolution order:
  1. RH_POOL_CONFIG env var -> explicit config JSON path
  2. <skill_dir>/skill-config.json
  3. Built-in defaults

The API key is NOT handled here; it is resolved by the existing runninghub
script helpers (env / secret / agent profile).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


# scripts/rh_pool/config.py -> scripts -> runninghub (skill dir)
SKILL_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = SKILL_DIR / "config"


@dataclass
class PollConfig:
    minIntervalMs: int = 30_000
    pacingMinMs: int = 30_000
    pacingMaxMs: int = 120_000


@dataclass
class PoolConfig:
    concurrency: int = 3
    dataDir: Path = field(default_factory=lambda: SKILL_DIR / "data" / "pool")
    defaultInstanceType: str = "default"
    notifyText: str = "任务批次已完成"
    poll: PollConfig = field(default_factory=PollConfig)

    @property
    def db_path(self) -> Path:
        return self.dataDir / "pool.sqlite"


def _config_path() -> Path | None:
    env_path = os.environ.get("RH_POOL_CONFIG")
    if env_path:
        p = Path(env_path)
        return p if p.exists() else None
    p = CONFIG_DIR / "skill-config.json"
    return p if p.exists() else None


def load_config() -> PoolConfig:
    cfg = PoolConfig()
    path = _config_path()
    raw: dict = {}
    if path:
        raw = json.loads(path.read_text(encoding="utf-8"))

    if "concurrency" in raw:
        cfg.concurrency = max(1, int(raw["concurrency"]))
    if "defaultInstanceType" in raw:
        cfg.defaultInstanceType = str(raw["defaultInstanceType"])
    if "notifyText" in raw:
        cfg.notifyText = str(raw["notifyText"])
    # Explicit env override for data dir is handy in dev / tests.
    data_dir = os.environ.get("RH_POOL_DATA_DIR") or raw.get("dataDir")
    if data_dir:
        p = Path(str(data_dir)).expanduser()
        # Relative paths resolve inside the skill folder (self-contained skill).
        cfg.dataDir = p if p.is_absolute() else SKILL_DIR / p
    poll_raw = raw.get("poll") or {}
    cfg.poll = PollConfig(
        minIntervalMs=int(poll_raw.get("minIntervalMs", cfg.poll.minIntervalMs)),
        pacingMinMs=int(poll_raw.get("pacingMinMs", cfg.poll.pacingMinMs)),
        pacingMaxMs=int(poll_raw.get("pacingMaxMs", cfg.poll.pacingMaxMs)),
    )
    return cfg
