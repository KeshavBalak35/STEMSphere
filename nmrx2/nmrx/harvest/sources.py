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
