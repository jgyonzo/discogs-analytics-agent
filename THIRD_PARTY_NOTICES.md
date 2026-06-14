# Third-Party Notices

This project (the "Software") is licensed under the MIT License (see
[`LICENSE`](./LICENSE)). The MIT License applies to the original source code,
configuration, and documentation authored in this repository.

It does **not** apply to the third-party data described below, which is
included for testing and demonstration purposes and remains subject to the
terms under which its respective source makes it available.

## Discogs Data

Portions of this repository are derived from the **Discogs monthly data
dumps** — specifically the sample/fixture files used by the ETL and agent
test suites, including (non-exhaustively):

- `etl/tests/fixtures/artists_sample_raw.xml`
- `etl/tests/fixtures/masters_sample_raw.xml`
- `etl/tests/fixtures/releases_sample_raw.xml`
- `etl/tests/fixtures/*_sample.xml` and other fixtures derived from the above
- `agent/tests/fixtures/seed.duckdb`,
  `agent/tests/fixtures/seed_no_master.duckdb` (built from the sample data)

**Source:** Discogs (https://www.discogs.com), data dumps published at
https://data.discogs.com/.

**License:** The Discogs data dumps are released by Discogs into the public
domain under the **Creative Commons CC0 1.0 Universal (CC0 1.0) Public Domain
Dedication** (https://creativecommons.org/publicdomain/zero/1.0/). See the
Discogs data page (https://www.discogs.com/data/) for the current terms.

**Trademark / attribution:** "Discogs" is a trademark of its respective owner.
Use of the name here is solely to identify the origin of the data and does not
imply any endorsement or affiliation.

**Personal data notice:** The Discogs dataset may contain personal information
(e.g., artist or label contact details that were publicly listed on Discogs).
Such data is included only as it appears in the public Discogs data dumps. If
you are a data subject and wish to have information removed, please open an
issue in this repository.
