"""Small, deterministic path context for season-scoped core data pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


DEFAULT_SEASON = "ss13"
_SEASON_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class SeasonContext:
    repo: Path
    season: str = DEFAULT_SEASON

    def __post_init__(self) -> None:
        if not _SEASON_RE.fullmatch(self.season):
            raise ValueError(f"invalid season id: {self.season!r}")
        object.__setattr__(self, "repo", self.repo.resolve())

    @property
    def source_root(self) -> Path:
        return self.repo / "sources" / "seasons" / self.season

    @property
    def system_manifest(self) -> Path:
        return self.source_root / "system_manifest.json"

    def source_manifest(self, system_id: str) -> Path:
        return self.source_root / f"{system_id}_manifest.json"

    @property
    def raw_manifest_root(self) -> Path:
        return self.repo / "data" / "raw" / "manifests" / self.season

    @property
    def entity_output(self) -> Path:
        return self.repo / "data" / "generated" / self.season / "entity-index-v3.json"

    @property
    def structured_root(self) -> Path:
        return self.repo / "data" / "generated" / "structured" / self.season

    @property
    def report_root(self) -> Path:
        return self.repo / "data" / "reports" / "local-wiki" / self.season

    @property
    def asset_root(self) -> Path:
        return self.repo / "data" / "raw" / "assets" / self.season

    @property
    def asset_manifest(self) -> Path:
        return self.asset_root / "asset-manifest.json"

    @property
    def i18n_root(self) -> Path:
        return self.repo / "data" / "raw" / "i18n" / self.season

    @property
    def mirror_output(self) -> Path:
        return self.repo / "local_wiki" / self.season / "site"

    def readable_system_manifest(self) -> Path:
        if self.system_manifest.is_file() or self.season != DEFAULT_SEASON:
            return self.system_manifest
        return self.repo / "sources" / "system_manifest.json"

    def readable_source_manifest(self, system_id: str) -> Path:
        scoped = self.source_manifest(system_id)
        if scoped.is_file() or self.season != DEFAULT_SEASON:
            return scoped
        return self.repo / "sources" / f"{system_id}_manifest.json"

    def readable_raw_manifest_root(self) -> Path:
        if self.raw_manifest_root.is_dir() or self.season != DEFAULT_SEASON:
            return self.raw_manifest_root
        return self.repo / "data" / "raw" / "manifests"

    def readable_entity_output(self) -> Path:
        if self.entity_output.is_file() or self.season != DEFAULT_SEASON:
            return self.entity_output
        return self.repo / "data" / "generated" / "entity-index-v3.json"

    def readable_i18n_file(self, relative: str = "files/i18n/cn.json") -> Path:
        scoped = self.i18n_root / relative
        if scoped.is_file() or self.season != DEFAULT_SEASON:
            return scoped
        return self.repo / "data" / "raw" / "i18n" / DEFAULT_SEASON / relative

    def readable_asset_manifest(self) -> Path:
        if self.asset_manifest.is_file() or self.season != DEFAULT_SEASON:
            return self.asset_manifest
        return self.repo / "data/raw/assets/ss13/asset-manifest.json"

    def readable_asset_files(self) -> Path:
        scoped = self.asset_root / "files"
        if scoped.is_dir() or self.season != DEFAULT_SEASON:
            return scoped
        return self.repo / "data/raw/assets/ss13/files"

    def readable_i18n_root(self) -> Path:
        scoped = self.i18n_root / "files"
        if scoped.is_dir() or self.season != DEFAULT_SEASON:
            return scoped
        return self.repo / "data/raw/i18n/ss13/files"

    def readable_structured_index(self) -> Path:
        scoped = self.structured_root / "structured-search-index.json"
        if scoped.is_file() or self.season != DEFAULT_SEASON:
            return scoped
        return self.repo / "data/generated/structured/ss13/structured-search-index.json"
