from __future__ import annotations

from datetime import datetime, timezone

from warehouse.naming import RESERVED_SCHEMAS, derive_section_name, slugify_base

TS = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


def test_slugify_basic():
    assert slugify_base("Sales Data (2024).csv") == "sales_data_2024"


def test_slugify_collapses_and_strips():
    assert slugify_base("__weird  ---name__.CSV") == "weird_name"


def test_slugify_empty_stem_falls_back():
    # "___.csv" has stem "___" which slugifies to empty -> fallback.
    assert slugify_base("___.csv") == "dataset"
    # ".csv" is a dotfile: pathlib stem is ".csv", so the slug is "csv".
    assert slugify_base(".csv") == "csv"


def test_slugify_non_alpha_start_gets_prefixed():
    assert slugify_base("123abc.csv").startswith("s_")


def test_slugify_truncates_long_names():
    assert len(slugify_base("a" * 200 + ".csv")) <= 40


def test_derive_appends_utc_timestamp():
    name = derive_section_name("Sales Data (2024).csv", TS)
    assert name == "sales_data_2024__20260611T120000Z"


def test_derive_naive_timestamp_treated_as_utc():
    naive = datetime(2026, 6, 11, 12, 0, 0)
    assert derive_section_name("x.csv", naive) == derive_section_name("x.csv", TS)


def test_derive_disambiguates_collision():
    base = derive_section_name("x.csv", TS)
    second = derive_section_name("x.csv", TS, existing={base})
    third = derive_section_name("x.csv", TS, existing={base, second})
    assert second == f"{base}_2"
    assert third == f"{base}_3"


def test_derive_avoids_reserved_schemas():
    name = derive_section_name("_locus.csv", TS, existing=set())
    assert name not in RESERVED_SCHEMAS
