"""Ad formats, loaded from formats.json (PRD: Platform formats)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class Multi(BaseModel):
    min: int
    max: int


class FieldSpec(BaseModel):
    key: str
    label: str
    recommended: int
    limit: int
    multi: Multi | None = None
    # X counts hashtags against the post itself.
    counts_hashtags: bool = False


class FormatSpec(BaseModel):
    key: str
    platform: str
    name: str
    image_direction: str | None
    max_hashtags: int
    fields: list[FieldSpec]


@lru_cache
def all_formats() -> dict[str, FormatSpec]:
    data = json.loads((Path(__file__).parent / "formats.json").read_text())
    return {f["key"]: FormatSpec.model_validate(f) for f in data["formats"]}


def get_format(key: str) -> FormatSpec:
    try:
        return all_formats()[key]
    except KeyError:
        raise KeyError(f"unknown format: {key}") from None
