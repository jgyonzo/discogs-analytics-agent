"""Format normalization per source spec §11.2."""
from __future__ import annotations

VALID_FORMAT_GROUPS: frozenset[str] = frozenset({
    "Vinyl", "CD", "Cassette", "Digital", "DVD/Blu-ray",
    "Shellac", "Box Set", "Other", "Unknown",
})

_FORMAT_GROUP_MAP: dict[str, str] = {
    "vinyl": "Vinyl",
    "lathe cut": "Vinyl",
    "acetate": "Vinyl",
    "flexi-disc": "Vinyl",
    "cd": "CD",
    "cassette": "Cassette",
    "file": "Digital",
    "dvd": "DVD/Blu-ray",
    "blu-ray": "DVD/Blu-ray",
    "shellac": "Shellac",
    "box set": "Box Set",
    "other": "Other",
    "unknown": "Unknown",
}

_VINYL_DESCRIPTIONS: frozenset[str] = frozenset({"LP", '12"', '10"', '7"'})


def derive_format_group(name_raw: str | None) -> tuple[str, bool]:
    """Map a raw ``format name`` to its bucket. Returns (group, was_mapped).

    Unknown names map to ``Other`` with was_mapped=False so callers can record a
    warning. Missing/empty names map to ``Unknown`` with was_mapped=False.
    """
    if name_raw is None:
        return ("Unknown", False)
    key = name_raw.strip().lower()
    if not key:
        return ("Unknown", False)
    mapped = _FORMAT_GROUP_MAP.get(key)
    if mapped is not None:
        return (mapped, True)
    return ("Other", False)


def derive_is_vinyl(format_group: str, descriptions: list[str]) -> bool:
    if format_group == "Vinyl":
        return True
    return any(d in _VINYL_DESCRIPTIONS for d in descriptions)


def derive_is_cd(format_group: str) -> bool:
    return format_group == "CD"


def derive_is_cassette(format_group: str) -> bool:
    return format_group == "Cassette"


def derive_is_digital(format_group: str) -> bool:
    return format_group == "Digital"


def derive_is_box_set(format_group: str, descriptions: list[str]) -> bool:
    if format_group == "Box Set":
        return True
    return "Box Set" in descriptions


def description_summary(descriptions: list[str]) -> str | None:
    """Concatenate descriptions with '; '. Returns None if there are none."""
    if not descriptions:
        return None
    nonempty = [d for d in descriptions if d]
    return "; ".join(nonempty) if nonempty else None
