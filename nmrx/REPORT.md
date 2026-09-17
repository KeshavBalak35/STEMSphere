# NMRx source expansion — status report

Date: 2026-09-17. Scope: the source-discovery and data-access layer only.

---

## 0. One thing to read first

**There was no existing NMRx code in this repository.** Not in the working tree, not on any
branch, not anywhere on this machine. The repo contained only the STEMSphere Streamlit site.

The handoff asked to continue from current NMRx working code and preserve existing
calibration, harvesting and `nmrx/data` work. None of it was reachable from this session, so
this is a **first implementation**, not a continuation. If that work exists elsewhere — a ZIP,
another machine, another repo — nothing here has been reconciled against it, and the two will
need merging before either is trusted.

---

## 1. Pilot results: actual requests and bytes

The already-authorized six-host pilot was run **once**, through the real code path.

| Host | Request | Result | Bytes |
|---|---|---|---|
| `pubchem.ncbi.nlm.nih.gov` | PUG REST, one CID, two properties | 403 at CONNECT | 0 |
| `nmrshiftdb.nmr.uni-koeln.de` | `/api-docs/` | 403 at CONNECT | 0 |
| `www.ebi.ac.uk` | ChEBI API docs index | 403 at CONNECT | 0 |
| `data.rcsb.org` | one PDB entry's metadata | 403 at CONNECT | 0 |
| `search.rcsb.org` | search endpoint | 403 at CONNECT | 0 |
| `www.bindingdb.org` | REST API documentation page | 403 at CONNECT | 0 |

**Totals: 6 requests, 0 bytes downloaded, 0 records retrieved.**

Exact error: `URLError: <urlopen error Tunnel connection failed: 403 Forbidden>`. The egress
proxy logged each as `connect_rejected — gateway answered 403 to CONNECT (policy denial)`.

This is a **host allowlist**, not an outage: a control fetch of `pypi.org` returned 200
normally in the same session. The refusal happens at CONNECT, before any path is sent, which
is why one request per host is sufficient and why blocked hosts are not re-probed.

Recorded in `nmrx/data/probes/pilot_probe_2026-09-17.json`.

The four NMR expansion hosts (`bmrb.io`, `api.bmrb.io`, `nmrxiv.org`,
`www.chemotion-repository.net`) were **deliberately not probed**. They are not granted in
project policy, and the project's own gate refuses them — which is the correct behaviour, so
it was left to happen.

---

## 2. Updated registry, and which entries have working adapters

All 50 sources are normalized in `nmrx/data/source_registry.json` with data types, host roles
(api / web / files / docs), access routes with documented-vs-inferred provenance, rights
evidence, NMR relevance and status.

**Status of every one of the 50: `documented_only`.** Nothing is `live_tested`, because
nothing can be. `automated_ingestion_approved` is `false` throughout.

Five sources have **adapter plans**: `nmrshiftdb2`, `bmrb`, `nmrxiv`, `chemotion`, `pubchem`.

None has a **working live adapter**, and none claims to. Every plan carries
`schema_confirmed: false`, and `fetch()` raises rather than running. What they do have is a
declarative routes-plus-field-mapping definition that parses offline and is exercised by
fixture tests. When a real response is finally read, the mapping JSON changes and
`schema_confirmed` flips — no new parser code.

This was a deliberate choice. Writing hand-rolled parsers against response shapes nobody has
ever seen would bake guesses into code and make them look verified.

---

## 3. The five capability questions, for the NMR priority four

| Source | 1. Find structure | 2. Retrieve measurements | 3. Assignments + conditions | 4. Establish rights | 5. Calibration eligible |
|---|---|---|---|---|---|
| **nmrshiftdb2** | partial | **yes** | partial | **no** | partial |
| **Chemotion** | partial | partial | unknown | partial | unknown |
| **nmrXiv** | unknown | partial | partial | **no** | unknown |
| **BMRB metabolomics** | unknown | partial | unknown | **no** | unknown |

`unknown` is a real verdict here, not a placeholder. It means the documentation does not
establish the answer and only a live call will.

**The single most important row is column 4.** Three of four score `no`. The sources with the
best NMR data have the least settled rights, and under the calibration gate a record with no
recorded licence fails at CAL-008 regardless of how good its spectrum is.

---

## 4. Coverage and missingness

Of 50 sources: 10 carry NMR, 8 of those claim measured evidence, and exactly **4** clear both
the assignment and condition bars — nmrshiftdb2, BMRB, nmrXiv, Chemotion. That is the whole
NMR-calibration surface in a 50-source directory.

Rights posture across all 50:

| Bucket | Count |
|---|---|
| Open licence stated, usable when unblocked | 19 |
| **Rights the research could not establish** | **20** |
| Non-commercial only | 3 |
| Licence, account or paid agreement required | 7 |
| Automated harvesting prohibited by the provider | 1 (SDBS) |

A consequence worth stating separately, because it is the sharpest number in this report.
39 sources carry no provider-side prohibition. But splitting that 39 by what the rights
actually say:

| | Count |
|---|---|
| Source-level open licence documented | **4** (ChEBI, COD, re3data, DataCite) |
| Usable only with a licence check on **every individual record** | 14 |
| Licence not established at all | 21 |

"No provider forbade it" is not permission. A source whose terms vary record by record has
settled nothing at the source level — MassBank's mandatory LICENSE field can read CC0 on one
record and non-commercial on the next — so it needs per-record gating in the ingestion code,
not a source-level judgement. And a source nobody has read the licence for fails the
calibration gate at CAL-008 regardless.

So **20 of 50** sources have rights the research could not establish — and that set includes
all four of the NMR priority sources. This is the largest single obstacle in the whole map, and
it is not a network problem.

**Record-level missingness is not yet measurable.** Zero real records have been retrieved, so
there is nothing to count. The machinery exists (`nmrx.reports.coverage.record_missingness`)
and is tested against synthetic records.

On the previous missing-metadata finding: it **cannot be audited yet**. Distinguishing a field
genuinely absent upstream from one dropped by an export or by our own mapping requires reading
a real response. Every missing field therefore starts as `unattributed` and can only be
narrowed by evidence. Guessing here is how a parser bug gets blamed on a database.

---

## 5. Best three next connectors

Computed by `python3 -m nmrx next`, from registry fields and recorded verdicts — not asserted.
Every score component is printed so the reasoning is inspectable.

**1. nmrXiv** — score 9.95. Host: `nmrxiv.org`.
The only source with documented search filters for **solvent, temperature and nucleus**, which
is exactly the metadata the calibration gate rejects records for lacking. Caveat the map is
explicit about: raw data plus acquisition metadata does **not** guarantee an assigned spectrum.
Licences are per project and per sample and propagate to spectra; they must not be read off the
site footer.

**2. Chemotion** — score 8.70. Host: `www.chemotion-repository.net`.
Best rights position of the four: per-publication licences that are actually stated (CC BY-SA
4.0, CC BY, CC0, public-domain marks). It also exposes a machine-readable API spec at
`/swagger_doc`, so the first live action is *read the schema*, not guess a route. Caveats: not
every spectrum has atom assignments, and some downloads may need registration — so metadata
and files must be tested separately.

**3. BMRB metabolomics** — score 7.90. Hosts: `bmrb.io`, `api.bmrb.io`.
Small-molecule NMR standards with shifts, experimental metadata and raw data. Held back by
rights: the metabolomics policy states free access but never names a reuse licence, so
assigning it CC0 would be an invention. The portal also mixes experimental with theoretical
entries, and that distinction must be read per record.

---

## 6. Remaining blockers, precisely

### Network (nothing else can proceed until this moves)

Six hostnames must be added to the **cloud environment's** Allowed domains — Network access →
Custom, one hostname per line. This is an environment setting. It cannot be changed from chat,
from this repo, or by any code:

```
pubchem.ncbi.nlm.nih.gov
nmrshiftdb.nmr.uni-koeln.de
www.ebi.ac.uk
data.rcsb.org
search.rcsb.org
www.bindingdb.org
```

Keep existing package-manager access. Two scope warnings before anyone pastes that list:

* **`www.ebi.ac.uk` is five services, not one.** It serves ChEMBL, ChEBI, UniChem, PDBe and
  the EBI-hosted Europe PMC. Allowlisting it grants all five.
* **`www.bindingdb.org` is one of three spellings** the provider's own material uses. The other
  two — `bindingdb.org` (no www, documented as carrying API endpoints) and `ww.bindingdb.org`
  (the download alias; `ww`, not a typo) — are different hostnames and are not granted. Which
  one the API actually uses is unconfirmed, because we cannot read the documentation page.

Bulk delivery leaves the granted host in four of six cases (`ftp.ncbi.nlm.nih.gov`,
`sourceforge.net`, `ftp.ebi.ac.uk`, `files.rcsb.org`). Cross-host redirects are refused rather
than followed, by design.

### Rights

* **nmrshiftdb2, BMRB, nmrXiv** — licence text unread. Blocks calibration export at CAL-008.
  For nmrshiftdb2 specifically: do **not** carry forward the earlier blanket share-alike claim.
  The provider's `License.txt` did not render during research and has not been read since.
* **Share-alike contagion** on ChEMBL (CC BY-SA 3.0), BindingDB's ChEMBL-derived subset,
  DrugCentral (CC BY-SA 4.0), ORD (version unstated), Chemotion per-publication, and IUPHAR
  (ODbL **plus** CC BY-SA 4.0). A share-alike database licence does not license NMRx's own
  application code — but it can attach obligations to data NMRx redistributes.
* **Non-commercial:** CAS Common Chemistry (CC BY-NC 4.0), SABIO-RK free tier, Wiley
  SpectraBase annotation export.
* **SDBS:** provider forbids robot collection. Permanently excluded, manual reference only.

### Schema

No adapter route has been confirmed against a real response. Every plan lists its outstanding
unknowns. For nmrshiftdb2 the map supplies only a Swagger index — no operation path, no
parameter name, no response schema.

---

## 7. What was not done, and why

* **No data was downloaded.** 0 bytes of chemical data.
* **No account created, no key requested, no licence agreed.**
* **No new hostname granted.** The pilot's six are unchanged; the four expansion hosts are
  assessed and explicitly *not* granted.
* **No blocked probe repeated.**
* **Caps are proposed, not inherited.** No numeric byte or request cap was recorded in the
  handoff material, so conservative defaults are enforced now (50 requests/job, 2 MB/response,
  10 MB/job) and flagged `proposed_default_awaiting_user_confirmation`. Raise them only on an
  explicit instruction.

---

## 8. Verification

282 offline tests pass: `python3 -m unittest discover -s tests -t .`

Standard library only. Among the checks that keep this report honest:

* every route marked `documented` is traceable verbatim to the research material — this caught
  one route that was not, and it was reclassified;
* the registry is never more permissive than the independent rights review;
* no source the research hedged is upgraded to a settled licence;
* no adapter claims a confirmed schema;
* granting `www.bindingdb.org` does not grant its two sibling spellings;
* a sparse record passes through the whole pipeline with its solvent, temperature and reference
  still `UNKNOWN`.

All fixtures are synthetic and labelled. No real API response has ever been observed here.
