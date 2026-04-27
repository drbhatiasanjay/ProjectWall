from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class Defaults(BaseModel):
    health_timeout_s: int = 30
    idle_shutdown_min: float = 45


class Project(BaseModel):
    id: str
    name: str
    category: Literal["local", "remote"] = "local"
    color: str = "#6E56CF"
    icon: str = "🧩"
    path: str
    stack: str
    command: list[str] = Field(default_factory=list)
    port: int | None = None
    health: str | None = None
    live_url: str | None = None
    obsidian: str | None = None
    # None = inherit defaults.idle_shutdown_min; 0 = never auto-stop this project
    idle_shutdown_min: float | None = None

    @field_validator("path")
    @classmethod
    def _expand_path(cls, v: str) -> str:
        return str(Path(v).expanduser())

    def rendered_command(self) -> list[str]:
        if self.port is None:
            return list(self.command)
        return [part.replace("{port}", str(self.port)) for part in self.command]

    def rendered_health(self) -> str | None:
        if not self.health or self.port is None:
            return self.health
        return self.health.replace("{port}", str(self.port))


class WallConfig(BaseModel):
    version: int = 1
    defaults: Defaults = Field(default_factory=Defaults)
    projects: list[Project]

    def get(self, project_id: str) -> Project | None:
        return next((p for p in self.projects if p.id == project_id), None)


def load_config(path: str | Path) -> WallConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return WallConfig.model_validate(data)
