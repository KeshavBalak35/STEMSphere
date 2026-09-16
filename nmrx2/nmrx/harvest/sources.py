"""Registry of public spectral and pharmacological data sources.

Licence terms decide what a commercial product may ingest, so they are recorded
next to the endpoint rather than in a document nobody reads. Every entry carries
`verified: False`. These summaries reflect the terms as understood at the time of
writing, they are not legal advice, and terms change. Confirm each source before
ingesting it into anything you sell.

`commercial_use` values:
  allowed      permissive licence, commercial use with attribution
  share_alike  commercial use is permitted. The obligation attaches to the DATABASE:
               if you redistribute the source database, or a derived database built
               from it, that redistribution may have to carry the same licence. It is
               not software copyleft and does not reach your application code, your
               calculations or your interface. Operating a paid service on top of it
               is a different question from publishing the data, and the two are
               frequently confused. Get the redistribution question reviewed.
  restricted   free for academic use, separate licence required to sell
  prohibited   terms forbid bulk retrieval or redistribution
"""

SOURCES = {
    "nmrshiftdb2": {
        "name": "NMRShiftDB2",
        "content": "Assigned 1H and 13C shifts with solvent and field, open submission",
        "modality": ["nmr"],
        "bulk": "https://nmrshiftdb.nmr.uni-koeln.de/",
        "format": "sdf",
        "licence": "CC BY-SA (database content)",
        "commercial_use": "share_alike",
        "bulk_download_allowed": True,
        "approximate_records": 44000,
        "note": "The anchor corpus: the only large open collection with per-atom assignments. "
                "Share-alike governs redistribution of the database, not the operation of a "
                "product built on it. The question to review is whether your calibration corpus "
                "counts as a derived database you would be redistributing, and what you would "
                "have to publish if it does. Your own code and calculations are unaffected.",
        "verified": False,
    },
    "cascade": {
        "name": "CASCADE (Paton lab)",
        "content": "About 5,100 molecules with BOTH experimental 13C shifts and DFT values at one "
                   "fixed level, plus 3D structures. The only public source found carrying both halves.",
        "modality": ["nmr"],
        "bulk": "https://raw.githubusercontent.com/patonlab/cascade/master",
        "format": "csv_sdf",
        "licence": "MIT repository; experimental shifts sampled from NMRShiftDB (CC BY-SA)",
        "commercial_use": "share_alike",
        "bulk_download_allowed": True,
        "approximate_records": 5139,
        "note": "The repository licence does not settle the underlying data's terms. Exp5K is the "
                "DFT-agreeing subset of NMR8K, so it is filtered by agreement and yields optimistic "
                "intervals. Do not join NMR8K to DFT8K by atom index; the numbering disagrees.",
        "verified": False,
    },
    "cheshire": {
        "name": "CHESHIRE NMR prediction benchmark sets",
        "content": "Curated probe and test sets pairing experimental 13C and 1H shifts with stated "
                   "computational protocols and scaling factors",
        "modality": ["nmr"],
        "bulk": "http://cheshirenmr.info/MoleculeSets.htm",
        "format": "html_tables",
        "licence": "Academic reference resource; terms not stated for redistribution",
        "commercial_use": "restricted",
        "bulk_download_allowed": False,
        "approximate_records": 100,
        "note": "The highest-quality match for the calibration layer of anything found: it exists "
                "specifically to benchmark computed shifts against experiment, and states the level "
                "of theory. Small, so it is a validation set rather than a training corpus. A subset "
                "ships inside the CASCADE repository. Confirm redistribution terms before shipping it.",
        "verified": False,
    },
    "gissmo": {
        "name": "GISSMO (BMRB)",
        "content": "1H spin systems with simulated and experimental spectra, field, solvent and pH",
        "modality": ["nmr"],
        "bulk": "https://gissmo.bmrb.io/",
        "format": "json_xml",
        "licence": "Public, free use (same terms as BMRB)",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": 1000,
        "note": "Conditions metadata is unusually complete. 1H only, and 1H calibration is harder "
                "than 13C because the shift range is narrow and solvent effects are proportionally "
                "larger. Useful second target, not the first.",
        "verified": False,
    },
    "chemotion": {
        "name": "Chemotion Repository",
        "content": "Open research-data repository fed by electronic lab notebooks; raw and processed "
                   "NMR with acquisition metadata",
        "modality": ["nmr", "ir", "ms"],
        "bulk": "https://www.chemotion-repository.net/",
        "format": "json_api",
        "licence": "CC BY per dataset in most cases",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": None,
        "note": "Because it is fed from lab notebooks, solvent and instrument conditions are recorded "
                "as a matter of course rather than as an afterthought. That is exactly the field this "
                "project is short of. Per-atom assignment depends on the depositor. Worth a survey.",
        "verified": False,
    },
    "nmredata": {
        "name": "NMReDATA format and record collections",
        "content": "An SDF extension that carries assigned shifts, couplings, solvent and temperature "
                   "inside the structure file",
        "modality": ["nmr"],
        "bulk": "https://nmredata.org/",
        "format": "sdf_nmredata",
        "licence": "The format is open; individual record sets vary",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": None,
        "note": "Strictly a file format rather than a database, and that is why it matters here: it is "
                "the one format that carries assignment AND conditions in a single file. Supporting it "
                "means data obtained by any route, a collaborator, a licence purchase or your own "
                "spectrometer, flows in without a new connector.",
        "verified": False,
    },
    "zenodo": {
        "name": "Zenodo and general research repositories",
        "content": "Individual deposited NMR datasets accompanying publications",
        "modality": ["nmr", "ir"],
        "bulk": "https://zenodo.org/",
        "format": "mixed",
        "licence": "Per deposit, commonly CC BY or CC0",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": None,
        "note": "Long tail. Quality and format vary per deposit and there is no common schema, so this "
                "is a manual, curated route rather than a connector. Each deposit needs its licence "
                "read individually.",
        "verified": False,
    },
    "nmrxiv": {
        "name": "nmrXiv",
        "content": "Open NMR datasets including raw FID and processed spectra",
        "modality": ["nmr"],
        "bulk": "https://nmrxiv.org/",
        "format": "json_api",
        "licence": "Per dataset, commonly CC BY",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": None,
        "note": "Licence varies per submission. Must be read per dataset, not assumed globally.",
        "verified": False,
    },
    "bmrb": {
        "name": "Biological Magnetic Resonance Data Bank",
        "content": "Mostly biomolecular; the metabolomics subset carries small-molecule 1H and 13C",
        "modality": ["nmr"],
        "bulk": "https://bmrb.io/",
        "format": "nmrstar",
        "licence": "Public, free use",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": None,
        "note": "Use the metabolomics subset. Protein chemical shifts are outside the closed-shell "
                "small-molecule domain the quantum engine supports.",
        "verified": False,
    },
    "hmdb": {
        "name": "Human Metabolome Database",
        "content": "Metabolites with experimental 1H and 13C, some predicted",
        "modality": ["nmr", "ms"],
        "bulk": "https://hmdb.ca/downloads",
        "format": "xml",
        "licence": "Free for academic use; commercial use requires a separate licence",
        "commercial_use": "restricted",
        "bulk_download_allowed": True,
        "approximate_records": 1500,
        "note": "Mixes experimental and predicted spectra. Predicted values must never enter a "
                "calibration corpus: calibrating a prediction against a prediction measures nothing.",
        "verified": False,
    },
    "riken_spectraldb": {
        "name": "RIKEN SpectralDB",
        "content": "NMR for natural products and metabolites",
        "modality": ["nmr"],
        "bulk": "http://spectra.psc.riken.jp/",
        "format": "html",
        "licence": "Free for academic use",
        "commercial_use": "restricted",
        "bulk_download_allowed": False,
        "approximate_records": None,
        "verified": False,
    },
    "pubchem": {
        "name": "PubChem",
        "content": "Structures and identifiers; spectral cross-references from depositors",
        "modality": ["structure"],
        "bulk": "https://ftp.ncbi.nlm.nih.gov/pubchem/",
        "format": "sdf",
        "licence": "Public domain (US government)",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": 119000000,
        "note": "Use for structure resolution and identifier crosswalk, not as a spectral source.",
        "verified": False,
    },
    "chembl": {
        "name": "ChEMBL",
        "content": "Bioactivity, ADMET endpoints, drug mechanism and pharmacokinetics",
        "modality": ["bioactivity"],
        "bulk": "https://ftp.ebi.ac.uk/pub/databases/chembl/",
        "format": "sqlite",
        "licence": "CC BY-SA 3.0",
        "commercial_use": "share_alike",
        "approximate_records": 2400000,
        "bulk_download_allowed": True,
        "note": "This is the source for the pharmacokinetic side of the product, not spectra.",
        "verified": False,
    },
    "wikidata": {
        "name": "Wikidata",
        "content": "Drug identifiers, cross-references, some physical properties",
        "modality": ["structure"],
        "bulk": "https://dumps.wikimedia.org/wikidatawiki/entities/",
        "format": "json",
        "licence": "CC0",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": None,
        "verified": False,
    },
    "cod": {
        "name": "Crystallography Open Database",
        "content": "Experimental crystal structures",
        "modality": ["structure"],
        "bulk": "https://www.crystallography.net/cod/",
        "format": "cif",
        "licence": "CC0",
        "commercial_use": "allowed",
        "bulk_download_allowed": True,
        "approximate_records": 500000,
        "note": "Useful as an independent geometry check on the conformer the engine selects.",
        "verified": False,
    },
    "drugbank": {
        "name": "DrugBank",
        "content": "Approved and investigational drugs, pharmacology, targets",
        "modality": ["bioactivity"],
        "bulk": "https://go.drugbank.com/releases/latest",
        "format": "xml",
        "licence": "CC BY-NC 4.0 for academic use",
        "commercial_use": "restricted",
        "bulk_download_allowed": True,
        "approximate_records": 16000,
        "note": "Non-commercial. A product with paying users needs the paid licence. Do not ingest first "
                "and negotiate later.",
        "verified": False,
    },
    "nist_webbook": {
        "name": "NIST Chemistry WebBook",
        "content": "Gas-phase IR, mass spectra, thermochemistry",
        "modality": ["ir", "ms"],
        "bulk": "https://webbook.nist.gov/chemistry/",
        "format": "jcamp",
        "licence": "Terms restrict systematic retrieval; much IR originates in copyrighted collections",
        "commercial_use": "prohibited",
        "bulk_download_allowed": False,
        "approximate_records": 16000,
        "note": "Gas-phase IR is the best possible match for a gas-phase harmonic calculation, which "
                "makes the access terms genuinely costly here. Ask NIST about a licence rather than scraping.",
        "verified": False,
    },
    "sdbs": {
        "name": "SDBS (AIST)",
        "content": "IR, 1H and 13C NMR, MS for tens of thousands of organics",
        "modality": ["nmr", "ir", "ms"],
        "bulk": "https://sdbs.db.aist.go.jp/",
        "format": "html",
        "licence": "Terms prohibit automated bulk download and redistribution",
        "commercial_use": "prohibited",
        "bulk_download_allowed": False,
        "approximate_records": 34000,
        "note": "The largest single collection matching the request, and closed. Scraping it puts a "
                "revenue-generating product in direct breach. Excluded by policy, not by capability.",
        "verified": False,
    },
    "commercial_spectral": {
        "name": "Wiley SpectraBase, Bio-Rad KnowItAll, ACD Labs",
        "content": "Large curated IR and NMR collections",
        "modality": ["nmr", "ir"],
        "bulk": None,
        "format": None,
        "licence": "Proprietary and copyrighted",
        "commercial_use": "prohibited",
        "bulk_download_allowed": False,
        "approximate_records": None,
        "note": "Licensable. For a calibration corpus a few hundred well-documented spectra may cost less "
                "than the engineering to assemble them from scattered open sources.",
        "verified": False,
    },
}

# ---------------------------------------------------------------------------
# Calibration fitness
#
# The calibration layer needs three things from a source, and a source missing any
# one of them cannot feed it however large it is:
#
#   measured        the values are measurements, not predictions. Calibrating a
#                   prediction against a prediction measures nothing.
#   assignments     each shift is tied to a specific atom. A peak list with no
#                   assignment cannot be paired with a computed shielding.
#   conditions      solvent and reference are recorded. Shifts are not comparable
#                   across solvents, and an unrecorded reference is an unknown
#                   offset applied to every value.
#
# Measured on the NMRShiftDB-derived bulk file: 6,032 molecules ingested, 601 with a
# recorded solvent, 0 with a recorded reference compound. Volume was never the
# constraint. This scoring exists so that ranking is done on the constraint.
# ---------------------------------------------------------------------------

CALIBRATION_FITNESS = {
    "nmrshiftdb2":   {"measured": "yes", "assignments": "yes", "conditions": "partial",
                      "detail": "Solvent recorded for about 10 percent of records, reference for none "
                                "in the sample examined. Assignments are per-atom and good."},
    "cascade":       {"measured": "yes", "assignments": "yes", "conditions": "partial",
                      "detail": "Carries BOTH measured shifts and DFT values at one fixed level, which "
                                "no other public source does. Filtered by agreement with the "
                                "calculation, so intervals fitted on it are optimistic."},
    "cheshire":      {"measured": "yes", "assignments": "yes", "conditions": "yes",
                      "detail": "Purpose-built for exactly this: benchmarking computed NMR against "
                                "experiment, with the computational protocol stated. Small, curated, "
                                "and the closest thing to a gold standard for scaling factors."},
    "bmrb":          {"measured": "yes", "assignments": "yes", "conditions": "yes",
                      "detail": "The metabolomics subset records solvent, pH, temperature and reference "
                                "properly. Small-molecule coverage is limited but the metadata is the "
                                "best of any open source."},
    "gissmo":        {"measured": "yes", "assignments": "yes", "conditions": "yes",
                      "detail": "1H spin systems with explicit field, solvent and pH. Narrow nucleus "
                                "coverage, excellent conditions."},
    "nmrxiv":        {"measured": "yes", "assignments": "partial", "conditions": "yes",
                      "detail": "Modern submissions carry full acquisition metadata. Per-atom "
                                "assignment depends on whether the depositor supplied NMReDATA."},
    "chemotion":     {"measured": "yes", "assignments": "partial", "conditions": "yes",
                      "detail": "Open repository fed by electronic lab notebooks, so conditions are "
                                "recorded as a matter of course. Assignment varies per dataset."},
    "hmdb":          {"measured": "mixed", "assignments": "partial", "conditions": "yes",
                      "detail": "Mixes experimental and predicted spectra in one place. The predicted "
                                "ones must be excluded explicitly or they will contaminate a corpus."},
    "riken_spectraldb": {"measured": "yes", "assignments": "partial", "conditions": "partial",
                      "detail": "No bulk access, so unusable at scale regardless of quality."},
    "sdbs":          {"measured": "yes", "assignments": "yes", "conditions": "yes",
                      "detail": "Scientifically ideal and legally closed. Bulk collection prohibited."},
    "nist_webbook":  {"measured": "yes", "assignments": "no", "conditions": "yes",
                      "detail": "Gas-phase IR is the best possible match for a gas-phase harmonic "
                                "calculation, which makes the access terms genuinely costly here."},
}

FITNESS_SCORE = {"yes": 2, "partial": 1, "mixed": 1, "no": 0}


def calibration_rank():
    """Rank sources by whether they can actually feed the calibration layer."""
    rows = []
    for key, fitness in CALIBRATION_FITNESS.items():
        source = SOURCES.get(key, {})
        score = sum(FITNESS_SCORE.get(fitness[f], 0) for f in ("measured", "assignments", "conditions"))
        reachable = bool(source.get("bulk_download_allowed"))
        rows.append({
            "source": key, "score": score, "measured": fitness["measured"],
            "assignments": fitness["assignments"], "conditions": fitness["conditions"],
            "bulk_access": reachable, "commercial_use": source.get("commercial_use", "unknown"),
            "records": source.get("approximate_records"),
            "usable_now": reachable and fitness["measured"] in ("yes", "mixed")
                          and fitness["assignments"] in ("yes", "partial"),
            "detail": fitness["detail"],
        })
    rows.sort(key=lambda r: (-r["score"], not r["usable_now"], r["source"]))
    return rows


def calibration_report():
    lines = ["Source          Score  Measured  Assign    Conditions  Bulk   Commercial     Usable",
             "-" * 92]
    for r in calibration_rank():
        lines.append("%-15s %d/6    %-9s %-9s %-11s %-6s %-14s %s" % (
            r["source"], r["score"], r["measured"], r["assignments"], r["conditions"],
            "yes" if r["bulk_access"] else "NO", r["commercial_use"],
            "yes" if r["usable_now"] else "no"))
    lines += ["", "Score is measured + assignments + conditions, 2 points each.",
              "'Usable' means bulk-accessible AND measured AND assigned. Conditions can be",
              "repaired by filtering; a missing assignment or a prediction cannot."]
    return "\n".join(lines)


HARVESTABLE = [k for k, v in SOURCES.items() if v["bulk_download_allowed"]]
COMMERCIALLY_CLEAR = [k for k, v in SOURCES.items()
                      if v["bulk_download_allowed"] and v["commercial_use"] == "allowed"]
SPECTRAL_AND_CLEAR = [k for k in COMMERCIALLY_CLEAR
                      if {"nmr", "ir"} & set(SOURCES[k]["modality"])]


def report():
    """Plain-text summary of what may be harvested and under which constraint."""
    lines = ["Source                 Modality        Bulk   Commercial    Records"]
    for key, s in sorted(SOURCES.items()):
        n = s["approximate_records"]
        lines.append("%-22s %-15s %-6s %-13s %s" % (
            key, ",".join(s["modality"]), "yes" if s["bulk_download_allowed"] else "NO",
            s["commercial_use"], format(n, ",") if n else "unknown"))
    lines.append("")
    lines.append("Harvestable: " + ", ".join(sorted(HARVESTABLE)))
    lines.append("Spectral and commercially unencumbered: " + (", ".join(sorted(SPECTRAL_AND_CLEAR)) or "none"))
    lines.append("Every entry is unverified. Confirm terms before ingesting into a commercial product.")
    return "\n".join(lines)
