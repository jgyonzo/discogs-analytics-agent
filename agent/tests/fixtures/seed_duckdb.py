"""Reproducible seed DuckDB builder.

Run as a script to materialize:
  - agent/tests/fixtures/seed.duckdb           (with master_fact)
  - agent/tests/fixtures/seed_no_master.duckdb (without master_fact)

The committed binaries are built from this script. CI re-runs the
script on every test session and asserts the structural shape against
the committed binaries (test_seed_duckdb_round_trip.py).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# Tiny, hand-built dataset spanning enough variety to test all golden
# query paths. Designed for ~30 rows in release_fact across 4 styles
# and 3 decades.

_RELEASES_BASE = [
    # (release_id, decade, year, country, has_vinyl, has_cd)
    (1001, 1980, 1985, "US", True, False),
    (1002, 1980, 1988, "DE", True, False),
    (1003, 1990, 1992, "UK", True, True),
    (1004, 1990, 1995, "US", False, True),
    (1005, 1990, 1998, "DE", True, True),
    (1006, 2000, 2002, "JP", False, True),
    (1007, 2000, 2005, "DE", True, True),
    (1008, 2000, 2008, "UK", True, True),
    (1009, 2010, 2012, "US", True, False),
    (1010, 2010, 2015, "DE", False, True),
    # 005-agent-schema-context: extra styles so the canonical-style
    # golden suite has a non-empty result for each name in
    # `agent/src/discogs_agent/llm/stub.py:_KNOWN_STYLES`.
    (1011, 1990, 1995, "UK", True, True),  # Ambient
    (1012, 2000, 2003, "UK", True, True),  # Drum n Bass
    (1013, 1990, 1996, "DE", True, True),  # Trance
    (1014, 1980, 1989, "JM", True, False),  # Dub
    (1015, 1990, 1994, "UK", True, False),  # Garage
    (1016, 1970, 1978, "US", True, False),  # Disco
    (1017, 1980, 1987, "UK", True, False),  # Acid Jazz
    (1018, 1970, 1973, "US", True, False),  # Funk
]

# (release_id, style, style_order)
_RELEASE_STYLES = [
    (1001, "Techno", 1),
    (1002, "Techno", 1),
    (1002, "House", 2),
    (1003, "Techno", 1),
    (1004, "House", 1),
    (1005, "Techno", 1),
    (1005, "House", 2),
    (1006, "House", 1),
    (1007, "Techno", 1),
    (1007, "Acid", 2),
    (1008, "Techno", 1),
    (1009, "House", 1),
    (1010, "Techno", 1),
    (1010, "Acid", 2),
    # Each canonical style gets at least one release in the seed.
    (1011, "Ambient", 1),
    (1012, "Drum n Bass", 1),
    (1013, "Trance", 1),
    (1014, "Dub", 1),
    (1015, "Garage", 1),
    (1016, "Disco", 1),
    (1017, "Acid Jazz", 1),
    (1018, "Funk", 1),
]

# (release_id, primary_genre)
_RELEASE_GENRES = {
    1001: "Electronic",
    1002: "Electronic",
    1003: "Electronic",
    1004: "Electronic",
    1005: "Electronic",
    1006: "Electronic",
    1007: "Electronic",
    1008: "Electronic",
    1009: "Rock",
    1010: "Electronic",
    1011: "Electronic",
    1012: "Electronic",
    1013: "Electronic",
    1014: "Reggae",
    1015: "Electronic",
    1016: "Funk / Soul",
    1017: "Jazz",
    1018: "Funk / Soul",
}

# (release_id, master_id) — a few releases share masters.
_RELEASE_MASTERS = {
    1001: 9001,
    1002: 9002,
    1003: 9003,
    1004: 9004,
    1005: 9005,
    1006: 9006,
    1007: 9001,  # reissue of master 9001
    1008: 9001,  # another reissue
    1009: 9007,
    1010: 9008,
}

# (release_id, label_name, label_order)
_RELEASE_LABELS = [
    (1001, "Underground Resistance", 1),
    (1002, "Tresor", 1),
    (1003, "Warp", 1),
    (1004, "Strictly Rhythm", 1),
    (1005, "Tresor", 1),
    (1006, "Studio Apartment", 1),
    (1007, "Tresor", 1),
    (1008, "Underground Resistance", 1),
    (1009, "Defected", 1),
    (1010, "Tresor", 1),
]

# (release_id, artist_name, artist_order)
_RELEASE_ARTISTS = [
    (1001, "Mad Mike", 1),
    (1002, "Jeff Mills", 1),
    (1003, "Aphex Twin", 1),
    (1004, "Frankie Knuckles", 1),
    (1005, "Cristian Vogel", 1),
    (1006, "Tom Trago", 1),
    (1007, "DJ Rolando", 1),
    (1008, "Underground Resistance", 1),
    (1009, "Defected Allstars", 1),
    (1010, "Aux 88", 1),
]

# Master fact rows.
_MASTERS = [
    # (master_id, title, main_release_id, year, primary_genre, primary_style, release_count)
    (9001, "Hi-Tech Jazz", 1001, 1985, "Electronic", "Techno", 3),
    (9002, "The Bells", 1002, 1988, "Electronic", "Techno", 1),
    (9003, "Selected Ambient Works", 1003, 1992, "Electronic", "Techno", 1),
    (9004, "Your Love", 1004, 1995, "Electronic", "House", 1),
    (9005, "Body Mapping", 1005, 1998, "Electronic", "Techno", 1),
    (9006, "Studio Apartment EP", 1006, 2002, "Electronic", "House", 1),
    (9007, "Defected House", 1009, 2012, "Rock", "House", 1),
    (9008, "Aux 88 reissue", 1010, 2015, "Electronic", "Techno", 1),
]


def _setup_release_fact(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE release_fact (
            release_id BIGINT,
            decade INTEGER,
            year INTEGER,
            country VARCHAR,
            has_vinyl BOOLEAN,
            has_cd BOOLEAN,
            style VARCHAR,
            style_order INTEGER,
            primary_genre VARCHAR,
            master_id BIGINT
        )
        """
    )
    rows: list[tuple] = []
    for r in _RELEASES_BASE:
        rid, decade, year, country, has_vinyl, has_cd = r
        master_id = _RELEASE_MASTERS.get(rid)
        primary_genre = _RELEASE_GENRES.get(rid)
        styles_for_r = [s for s in _RELEASE_STYLES if s[0] == rid]
        for _, style, style_order in styles_for_r:
            rows.append(
                (
                    rid,
                    decade,
                    year,
                    country,
                    has_vinyl,
                    has_cd,
                    style,
                    style_order,
                    primary_genre,
                    master_id,
                )
            )
    con.executemany(
        "INSERT INTO release_fact VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _setup_release_unique_view(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE VIEW release_unique_view AS
        SELECT
            release_id,
            ANY_VALUE(decade)        AS decade,
            ANY_VALUE(year)          AS year,
            ANY_VALUE(country)       AS country,
            ANY_VALUE(has_vinyl)     AS has_vinyl,
            ANY_VALUE(has_cd)        AS has_cd,
            ANY_VALUE(primary_genre) AS primary_genre,
            ANY_VALUE(master_id)     AS master_id
        FROM release_fact
        GROUP BY release_id
        """
    )


def _setup_bridges(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE release_artist_bridge (
            release_id BIGINT,
            artist_name VARCHAR,
            artist_order INTEGER
        )
        """
    )
    con.executemany(
        "INSERT INTO release_artist_bridge VALUES (?, ?, ?)",
        _RELEASE_ARTISTS,
    )

    con.execute(
        """
        CREATE TABLE release_label_bridge (
            release_id BIGINT,
            label_name VARCHAR,
            label_order INTEGER
        )
        """
    )
    con.executemany(
        "INSERT INTO release_label_bridge VALUES (?, ?, ?)",
        _RELEASE_LABELS,
    )


def _setup_master_fact(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE master_fact (
            master_id BIGINT,
            title VARCHAR,
            main_release_id BIGINT,
            year INTEGER,
            primary_genre VARCHAR,
            primary_style VARCHAR,
            release_count INTEGER
        )
        """
    )
    con.executemany(
        "INSERT INTO master_fact VALUES (?, ?, ?, ?, ?, ?, ?)",
        _MASTERS,
    )


def build_seed_duckdb(target: Path, *, with_master_fact: bool) -> None:
    """Build the seed DuckDB at `target`. Idempotent — overwrites."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    con = duckdb.connect(str(target))
    try:
        _setup_release_fact(con)
        _setup_release_unique_view(con)
        _setup_bridges(con)
        if with_master_fact:
            _setup_master_fact(con)
    finally:
        con.close()


def main() -> None:
    here = Path(__file__).parent
    build_seed_duckdb(here / "seed.duckdb", with_master_fact=True)
    build_seed_duckdb(here / "seed_no_master.duckdb", with_master_fact=False)
    print(f"Built {here / 'seed.duckdb'} and {here / 'seed_no_master.duckdb'}")


if __name__ == "__main__":
    main()
