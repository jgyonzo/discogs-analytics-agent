"""Unit tests for format normalization (source spec §11.2)."""
from __future__ import annotations

import pytest

from discogs_etl.transforms.format_normalization import (
    VALID_FORMAT_GROUPS,
    derive_format_group,
    derive_is_box_set,
    derive_is_cassette,
    derive_is_cd,
    derive_is_digital,
    derive_is_vinyl,
    description_summary,
)


@pytest.mark.parametrize("raw,expected_group", [
    ("Vinyl", "Vinyl"),
    ("Lathe Cut", "Vinyl"),
    ("Acetate", "Vinyl"),
    ("Flexi-disc", "Vinyl"),
    ("CD", "CD"),
    ("Cassette", "Cassette"),
    ("File", "Digital"),
    ("DVD", "DVD/Blu-ray"),
    ("Blu-ray", "DVD/Blu-ray"),
    ("Shellac", "Shellac"),
    ("Box Set", "Box Set"),
])
def test_known_format_names_map_correctly(raw, expected_group):
    group, was_mapped = derive_format_group(raw)
    assert group == expected_group
    assert was_mapped is True
    assert group in VALID_FORMAT_GROUPS


def test_unmapped_format_name_falls_back_to_other():
    group, was_mapped = derive_format_group("Floppy")
    assert group == "Other"
    assert was_mapped is False


@pytest.mark.parametrize("raw", [None, ""])
def test_missing_format_name_is_unknown(raw):
    group, was_mapped = derive_format_group(raw)
    assert group == "Unknown"
    assert was_mapped is False


def test_is_vinyl_from_format_group():
    assert derive_is_vinyl("Vinyl", []) is True
    assert derive_is_vinyl("CD", []) is False


@pytest.mark.parametrize("desc", ["LP", '12"', '10"', '7"'])
def test_is_vinyl_from_description(desc):
    # Even with a non-Vinyl group, classic vinyl descriptions imply vinyl.
    assert derive_is_vinyl("Other", [desc]) is True


def test_is_cd_only_from_group():
    assert derive_is_cd("CD") is True
    assert derive_is_cd("Vinyl") is False


def test_is_cassette_and_digital():
    assert derive_is_cassette("Cassette") is True
    assert derive_is_digital("Digital") is True
    assert derive_is_cassette("CD") is False
    assert derive_is_digital("CD") is False


def test_is_box_set_from_group_or_description():
    assert derive_is_box_set("Box Set", []) is True
    assert derive_is_box_set("Vinyl", ["Box Set"]) is True
    assert derive_is_box_set("CD", ["Album"]) is False


def test_description_summary_concat():
    assert description_summary([]) is None
    assert description_summary(["LP"]) == "LP"
    assert description_summary(["LP", '33 ⅓ RPM']) == 'LP; 33 ⅓ RPM'
    assert description_summary(["", None]) is None  # type: ignore[list-item]
