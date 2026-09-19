# NMRx reconciliation — Phase 1 inventory

**Date:** 19 September 2026
**Working repository:** `/home/user/STEMSphere` → `KeshavBalak35/STEMSphere`, branch
`claude/untitled-session-60gus3`
**Status: Phase 1 is incomplete, and Phases 2–3 cannot start. One of the two inputs is missing.**

---

## 1. The blocker, first

The reconcile prompt lists three inputs:

| Input | Arrived? |
|---|---|
| `NMRx_HANDOFF.md` | ✅ yes (as the review's subject; the content is also in this repo) |
| `nmrx-source-layer.zip` | ✅ yes — and it is already unpacked in this repo, so nothing to import |
| **`NMRx2_updated (1).zip`** | ❌ **no** |

The earlier backend never reached this machine. Checked:

- the uploads folder holds only four files — the two chemistry research documents from
  17 September, the reconcile prompt, and the review. No zip.
- `find / -iname "*nmrx2*"` returns nothing.
- the repository contains no FastAPI app, no SQLite job store, no worker, no docking or quantum
  code. `grep -rl "fastapi\|FastAPI" --include=*.py .` returns nothing.

**A reconciliation needs both codebases. I have one.** Everything below is what could be done
without the second, plus a plan that is explicitly provisional until the zip arrives.

### What to send

Re-upload `NMRx2_updated (1).zip`. If it is too large to attach, either of these also works:

- push it to a branch on `KeshavBalak35/STEMSphere` (or any repo I can be given access to) and
  tell me the branch name; or
- send just the structure to begin with — `find . -name "*.py" | sort` and the contents of
  `requirements.txt` / `pyproject.toml` — which is enough for me to finish the import-conflict
  table and firm up the merge plan, though not enough to implement it.

---

## 2. What is present: the source-access layer

One Python package, `nmrx/`, 3,850 lines across 20 modules, plus 320 tests.
**Standard library only** — the complete set of imports is `argparse, collections, copy,
dataclasses, datetime, enum, json, math, pathlib, ssl, sys, threading, time, typing, urllib`.
No third-party dependency, so it cannot conflict with the backend's requirements.

| Subpackage | Modules | Lines | What it does |
|---|---|---|---|
| `nmrx.sources` | `policy`, `http`, `probe`, `registry` | 1,138 | Which hosts may be called, byte/request caps, the bounded client, reachability probing, the 50-source registry |
| `nmrx.model` | `provenance`, `records`, `calibration`, `dedup`, `dossier` | 1,329 | Provenance vocabulary, NMR record types, the nine-rule calibration gate, cross-aggregator dedup, per-molecule dossier |
| `nmrx.adapters` | `base` + 5 JSON mapping plans | 492 | Declarative routes + field mapping, generic mapping engine |
| `nmrx.reports` | `coverage`, `blockers`, `ranking` | 614 | Coverage/missingness, blocker report, computed connector ranking |
| `nmrx.cli` | | 206 | `python -m nmrx <command>` |

Data lives in `nmrx/data/`: `access_policy.json`, `source_registry.json` (50 sources),
`rights_review.json`, `vocabulary.json`, `research_urls.json`, probe artifacts.

### What it does NOT contain

No web API, no job store, no worker, no chemistry preparation, no quantum/NMR/IR calculation,
no docking, no guide, no UI, and no harvest execution. It decides *whether and how* a source may
be contacted and *whether a record is trustworthy*. It does not compute anything chemical.

---

## 3. The conflict, as far as it can be assessed

**Caveat: this section is second-hand.** It is derived from the handoff review's description of
the earlier backend, not from reading that code. Treat every row as unconfirmed.

| Concern | Earlier backend (per review) | This source layer | Conflict? |
|---|---|---|---|
| Top-level package name | `nmrx` (under `nmrx2/`) | `nmrx` | **Yes — direct collision.** Copying either over the other loses code and creates import ambiguity |
| Web API | FastAPI app | none | No — complementary |
| Job store | SQLite | none | No |
| Worker | present | none | No |
| Chemistry prep | present | none | No |
| Quantum / NMR / IR | present | none | No |
| Docking | present | none | No |
| Guide / UI | present | none | No |
| **Harvest modules** | present | `sources/` + `adapters/` | **Likely overlap** — both concern fetching from external sources. This is the one place where real duplication is plausible, and it cannot be assessed without the code |
| Source registry / access policy | unknown | present | Unknown |
| Provenance / calibration gate | unknown | present | Unknown |

The single hard conflict I can confirm is the **package name**. The likely soft conflict is
**harvest**, and resolving it properly means reading the earlier harvest modules — not guessing.

---

## 4. Phase 2 — provisional merge plan

**Not to be implemented until the zip arrives and Section 3 is confirmed from the real code.**

### Recommendation: separate package boundary, not a directory merge

Two options were considered.

**Option A — fold the source layer into the backend's existing `nmrx` package**
as `nmrx/sources/`, `nmrx/provenance/`, etc.

*Against it:* the backend already has modules under `nmrx/`, including harvest code. Merging two
packages that share a root means every inner name is a potential collision, and the failure mode
is silent — an import resolves to the wrong module and something subtly misbehaves. It also makes
the change hard to reverse, which the prompt explicitly asks to avoid.

**Option B — keep the source layer as its own top-level package, imported by the backend.**
Rename this package `nmrx_sources` (or similar), leave the backend's `nmrx/` **byte-identical**,
and have the API import from the new package.

*For it:* the backend keeps working because nothing in it changes. There is no name collision at
any depth. The change is reversible by deleting one directory and one import. And the boundary is
honest — the source layer is a policy/provenance gate, not chemistry, so a separate name reflects
what it actually is.

**Recommendation: Option B.** Converging into one package can happen later, once both halves are
in one repo and the harvest overlap is understood. Doing it first risks the working backend for no
immediate gain.

### Proposed moves (provisional)

```
STEMSphere/
  nmrx2/nmrx/              ← the earlier backend, UNCHANGED (API, worker, chemistry, docking)
  nmrx_sources/            ← this layer, renamed from nmrx/ (git mv, history preserved)
    sources/ model/ adapters/ reports/ data/ cli.py
  tests/
    backend/               ← the earlier backend's tests, unchanged
    sources/               ← these 320 tests, import path updated
```

Import changes are mechanical and confined to this layer: `from nmrx.x import y` →
`from nmrx_sources.x import y`, about 60 import lines plus the `python -m nmrx` entry point.
**Zero edits inside the earlier backend.**

### How the API would call the source layer

Three read-only endpoints, none of which fetch anything:

| Endpoint | Returns | Backed by |
|---|---|---|
| `GET /sources` | the 50-source registry with tier, rights and status | `sources.registry` |
| `GET /sources/access` | which hosts are granted, which are blocked, and at which layer | `reports.blockers` |
| `GET /molecules/{id}/dossier` | per-field status incl. `access_blocked` | `model.dossier` |

The critical contract: when a source could not be consulted, the dossier must report
`access_blocked` and **not** `not_found`. That distinction already exists and is tested
(`tests/test_dossier.py::test_blocked_is_not_reported_as_not_found`). An API-level integration
test asserting it survives serialisation is required by the prompt and will be added in Phase 3 —
it cannot be written before the API exists.

### What I need from the zip to finalise this

1. `find . -name "*.py" | sort` — the real module layout.
2. The harvest modules, to decide whether they are replaced by, wrap, or sit beside this layer.
3. `requirements.txt` / `pyproject.toml` — dependency overlap and Python version.
4. How the FastAPI app is assembled (single file or routers) — determines where endpoints attach.
5. The job-store schema, if provenance fields need to persist alongside job results.

---

## 5. What was done outside the merge

Three defects the review raised are in **this** layer and do not depend on the backend, so they
are fixed and committed (`d2606b8`). None of them touched policy, licences or network behaviour.

1. **Atom indices were being rounded.** `_to_int(1.8)` returned `1`. That does not lose a little
   precision — it silently repoints a chemical shift at a different atom, and the result still
   looks like a valid mapping. Non-integral values now yield `UNKNOWN` and the peak stays
   unassigned. Booleans are rejected too, because `int(True)` is `1`.
   *Also found:* `_to_int(float('inf'))` raised `OverflowError`, breaking the "transforms are
   total" contract the mapping engine depends on.

2. **Redirect targets leaked credentials.** A refused redirect copied the raw `Location` header
   into the error text and the request log, bypassing the redaction applied to the original URL.
   `Location` is now redacted identically.
   *Correction to the record:* an earlier commit (`8bc9c7d`) claimed to have made the redirect
   message distinguish same-host from cross-host targets. **That patch never applied** — the
   anchor had drifted and the edit silently did nothing, so the commit message was wrong. It is
   fixed now, and the patch asserts before writing so it cannot fail quietly again.

3. **The dossier trusted identity instead of computing it.** Exact-vs-related was decided by
   reading each record's pre-populated `identity_match`, which arrives from an adapter mapping
   nobody has confirmed. A record could assert "exact" and be filed as a measurement of the
   submitted molecule with nothing checking the structures.

   Identity is now **computed** from submitted vs record. The claim is kept and reported, the
   computed verdict decides placement, and disagreements surface in a new
   `identity_claims_rejected` section. Splitting is three-way now: a record whose identity cannot
   be computed is neither exact nor related, because filing it as "related" would assert a
   relationship nobody established.

**320 tests pass** (`python3 -m unittest discover -s tests -t .`), up from 302.

---

## 6. Standing constraints — unchanged

No network domain was added. No live probe was run. No bulk data was downloaded. No licence
classification was changed. Nothing was deleted, renamed or replaced. Every adapter still has
`schema_confirmed: false`. Unknown values remain `UNKNOWN`. SDBS remains permanently prohibited.
No retry logic or proxy workaround was added for the CONNECT 403.

**NMRx still cannot access any dataset.** All six pilot hosts remain refused at CONNECT with
zero bytes retrieved, and no bounded pilot request has returned through any application.
