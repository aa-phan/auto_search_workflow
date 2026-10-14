# Third-party data notices

The board registry can be seeded from two public company inventories. Only *identifiers of
company job boards* are read from them; no posting, status, count or company description is
copied. Every job is fetched from the ATS's own public endpoint.

| Source | License | Used file(s) |
|---|---|---|
| [veresk06/open-ats-feed](https://github.com/veresk06/open-ats-feed) | MIT, Copyright (c) 2026 open-ats-feed contributors | `actor/data/companies.json` |
| [kalil0321/ats-scrapers](https://github.com/kalil0321/ats-scrapers) | MIT, Copyright (c) 2026 Kalil Bouzigues | `ats-companies/*.csv` |

Both licenses permit this use provided the copyright and permission notice is kept with
copies or substantial portions. This project does not redistribute their files; the importer
downloads them at run time and keeps a private last-known-good cache (`state/inventory/`,
git-ignored). Per-board provenance records which source listed each board.

Note: the open-ats-feed README describes its data as "public domain" while its `LICENSE` file
is MIT. We follow the license file.

Other ATS providers named in those lists (for example Breezy, Recruitee, Teamtailor, Workday,
Personio) are reported but not imported: this project has no adapter for them.
