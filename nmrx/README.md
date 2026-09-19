# NMRx source layer

This package is the part of NMRx that decides **where chemical data may come from, what we
are allowed to do with it, and whether a spectrum is good enough to calibrate against.**

It does not do quantum chemistry. It is the layer underneath that.

Nothing here changes the existing STEMSphere Streamlit site (`app.py`).

---

## Try it in one minute

From the repository root:

```bash
python3 -m nmrx coverage     # what data we have routes and rights for
python3 -m nmrx policy       # which hosts NMRx is actually allowed to call
python3 -m nmrx blockers     # what is blocking each source, and who can fix it
python3 -m nmrx rules        # why a spectrum gets rejected from calibration
python3 -m nmrx registry     # all 50 candidate sources
python3 -m nmrx registry nmrshiftdb2   # one source in full
```

Run the tests:

```bash
python3 -m unittest discover -s tests -t .
```

No installation, no dependencies. Standard library only.

---

## The two gates (this is the important part)

Before NMRx can fetch anything from a database, **two separate doors must both be open.**
People mix these up constantly, so the code keeps them apart:

| Gate | Where it lives | Who opens it |
|---|---|---|
| 1. Project policy | `nmrx/data/access_policy.json` | us, by editing that file |
| 2. Environment network | Claude Code cloud environment → Network access → Custom → Allowed domains | the environment owner, in settings |

**Being listed in the source registry grants nothing.** The registry is a research directory
of 50 candidate databases. `access_policy.json` is the only thing that grants a host, and even
then the environment can still refuse the connection.

Right now gate 2 is closed for every chemistry host. See `python3 -m nmrx blockers`.

Three rules the policy enforces that are easy to get wrong:

* **Hostname matching is exact.** `www.bindingdb.org` being granted does not grant
  `bindingdb.org` or `ww.bindingdb.org`. The provider's own documentation uses all three, and
  a suffix match would widen the pilot without anyone deciding to.
* **SDBS is permanently prohibited.** Its disclaimer forbids robot collection. It never
  becomes "not yet granted" — it is a different state.
* **Licensed sources refuse before a socket opens.** DrugBank, CAS Common Chemistry, Wiley
  SpectraBase, CSD, SABIO-RK, IUPHAR and NIST fail at the policy layer, not at the network.

---

## Unknown stays unknown

The second rule the code enforces for you.

If a database does not tell us the solvent, NMRx stores `UNKNOWN` — a real sentinel value,
not `None`, not an empty string, and never a plausible default like `"CDCl3"`. An invented
solvent silently corrupts a calibration set, and it is almost impossible to find afterwards.

If a condition is recovered later — from the paper, or from a documented convention of that
database — it must be wrapped with where it came from:

```python
from nmrx.model import Provenanced, ValueOrigin

solvent = Provenanced(
    value="CDCl3",
    origin=ValueOrigin.RECOVERED_FROM_PUBLICATION,
    evidence="doi:10.1000/example",     # required -- construction fails without it
)
```

Recovery without a citation raises an error, because it is indistinguishable from invention.

---

## Four things that must never be merged

The source research is emphatic about these, and every record carries all four
independently:

| Axis | Values |
|---|---|
| How the number was produced | measured · quantum calculated · model predicted · literature extracted |
| How finished the spectrum is | raw · processed · unassigned peaks · assigned peaks · image only |
| Whether this is the experiment | original experiment · mirrored copy · reprocessed version |
| How the molecule relates to ours | exact · different protonation / salt / tautomer / isotope / stereoisomer · connectivity only |

The third one has a consequence people miss: **the same PDB entry served by RCSB and by PDBe
is one experiment, not two.** `nmrx.model.dedup` collapses those for counting while keeping
every source that served them, so a dossier never claims corroboration it does not have.

---

## The calibration gate

`python3 -m nmrx rules` prints the current rules. A record must pass **all nine** to enter a
strict calibration export.

A record that fails is not thrown away. It stays **discovery-usable** — shown in a dossier,
clearly labelled, as source-attributed context. The one exception is `CAL-007`: an atom
mapping that is actually *wrong* (an index outside the molecule, or two shifts claiming the
same atom) is not shown at all. Incomplete is fine to display. Wrong is not.

---

## Why the adapters are JSON and not Python

No chemistry host is reachable from this environment, so **no real API response has ever been
observed here.** Writing hand-rolled parsers against guessed response shapes would bake
guesses into code and make them look verified.

Instead an adapter is a *plan*: routes plus a field mapping, stored as JSON with a
`schema_confirmed` flag. One generic engine turns any payload into records by following that
mapping. When someone finally reads a real response, they edit the JSON — no new parser code —
and flip `schema_confirmed` to `true`.

Until then, `adapter.fetch(...)` refuses to run and tells you exactly what is unconfirmed.
`adapter.parse(payload)` still works offline, which is what the fixture tests exercise.

Every route records its own provenance:

* `documented` — this exact URL appears in the source research material. A test asserts this.
* `inferred` — composed from a description of the service. The path is a guess until confirmed.

---

## Layout

```
nmrx/
  data/
    access_policy.json      the ONLY thing that grants a host
    source_registry.json    50 candidate sources (a directory, not a permission)
    pilot_probe_plan.json   one minimal request per granted host
    probes/                 what actually happened on the wire, with byte counts
  sources/
    policy.py               host grants, byte/request caps, per-host throttle
    http.py                 byte-capped client; caps abort mid-transfer
    probe.py                reachability probe with honest failure classification
    registry.py             registry loading, queries, contract validation
  model/
    provenance.py           the four axes, UNKNOWN, Provenanced
    records.py              molecule, conditions, shift assignment, NMR record
    calibration.py          the nine-rule strict gate
    dedup.py                cross-aggregator clustering that preserves lineage
  adapters/
    base.py                 declarative plans and the mapping engine
    mappings/               one JSON plan per source
  reports/
    coverage.py             source coverage and record missingness
    blockers.py             what is blocked, at which layer, and who can fix it
```

---

## What this layer deliberately does not claim

* That any source is licensed for reuse. `rights.status` records what provider documentation
  *says*. `unverified` is a real state and appears on nmrshiftdb2, BMRB, RRUFF, QCArchive and
  NMRBank because their licence text could not be read.
* That any route works. Nothing has been live-tested. Every registry entry is
  `documented_only`.
* That a molecule will have data. For a molecule never synthesised, measurements of that exact
  structure may simply not exist. A related compound can inform a comparison; it can never be
  presented as a measurement of the submitted molecule.
