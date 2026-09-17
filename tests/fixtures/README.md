# Test fixtures

**Every file here is synthetic.** None of it was captured from a real chemical database.

No chemistry host is reachable from this environment (the egress policy answers 403 to
CONNECT), so no real API response has been observed. These fixtures exist to exercise the
*mapping engine* — that a declared field mapping produces the right record shape, that absent
fields become `UNKNOWN` rather than defaults, and that the calibration gate rejects what it
should.

The shift values, identifiers and record ids are made up. They are not measurements and must
never be copied into a registry, a dossier or a calibration export.

When a real response is finally observed, save it here under `captured/` with the exact
request URL and retrieval date, set `schema_confirmed: true` in the matching
`nmrx/adapters/mappings/<source>.json`, and keep these synthetic files for the engine tests.
