from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Molecule(Strict):
    smiles: str = Field(min_length=1, max_length=2000)
    conformers: int = Field(default=5, ge=1, le=20)
    seed: int = Field(default=42, ge=1, le=2147483647)

class Quantum(Molecule):
    task: Literal["orbitals", "ir", "nmr"] = "orbitals"
    method: Literal["HF", "B3LYP", "PBE0"] = "B3LYP"
    basis: Literal["sto-3g", "def2-svp", "def2-tzvp"] = "def2-svp"
    optimize: bool = True
    displacement_bohr: float = Field(default=0.005, ge=0.001, le=0.02)
    reference_shielding_ppm: dict[str, float] = Field(default_factory=dict)
    reference_provenance: str | None = Field(default=None, max_length=2000)
    @model_validator(mode="after")
    def check(self):
        if self.task == "ir" and not self.optimize:
            raise ValueError("IR requires an optimized geometry")
        if self.reference_shielding_ppm and not self.reference_provenance:
            raise ValueError("Record reference method, basis, geometry, and environment")
        return self

class Docking(Molecule):
    receptor_pdbqt: str = Field(min_length=50, max_length=2000000)
    center_angstrom: tuple[float, float, float]
    box_angstrom: tuple[float, float, float] = (20, 20, 20)
    exhaustiveness: int = Field(default=8, ge=1, le=32)
    poses: int = Field(default=5, ge=1, le=20)
    preparation_notes: str = Field(min_length=10, max_length=2000)
    @model_validator(mode="after")
    def box(self):
        if any(x < 5 or x > 40 for x in self.box_angstrom):
            raise ValueError("Box dimensions must be 5–40 angstrom")
        return self

class Evidence(Strict):
    observed: list[float] = Field(min_length=2, max_length=500)
    predicted: list[float] = Field(min_length=2, max_length=500)
    sigma: list[float] = Field(min_length=2, max_length=500)
    modality: Literal["nmr_ppm", "ir_cm-1"]
    assignment_provenance: str = Field(min_length=5, max_length=1000)
    @model_validator(mode="after")
    def lengths(self):
        if not len(self.observed) == len(self.predicted) == len(self.sigma):
            raise ValueError("Inputs must have equal lengths and explicit matched assignments")
        if any(x <= 0 for x in self.sigma):
            raise ValueError("Standard deviations must be positive")
        return self

class Guide(Strict):
    question: str = Field(min_length=1, max_length=4000)
    job_id: str | None = None
    use_external_ai: bool = False

class Nucleus(Strict):
    index: int = Field(ge=0, le=999)
    shielding_ppm: float
    observed_shift_ppm: float

class CalibrationRecord(Strict):
    id: str = Field(min_length=1, max_length=200)
    smiles: str | None = Field(default=None, max_length=2000)
    nuclei: list[Nucleus] = Field(min_length=1, max_length=400)

class CalibrationProvenance(Strict):
    method: str = Field(min_length=1, max_length=100)
    basis: str = Field(min_length=1, max_length=100)
    nucleus: str = Field(min_length=1, max_length=20)
    solvent: str = Field(min_length=1, max_length=100)
    reference_compound: str = Field(min_length=1, max_length=100)
    temperature_k: float | None = Field(default=None, gt=0, le=1000)
    source: str | None = Field(default=None, max_length=2000)
    computed_kind: Literal["shielding", "shift"] = "shielding"

class CalibrationSet(Strict):
    provenance: CalibrationProvenance
    records: list[CalibrationRecord] = Field(min_length=2, max_length=5000)
    alpha: float = Field(default=0.05, gt=0.001, lt=0.5)
    train_fraction: float = Field(default=0.5, gt=0.05, lt=0.95)
    seed: int = Field(default=42, ge=1, le=2147483647)
    @model_validator(mode="after")
    def unique(self):
        ids = [r.id for r in self.records]
        if len(set(ids)) != len(ids):
            raise ValueError("Calibration record ids must be unique")
        return self

class CalibratedShifts(Strict):
    calibration: CalibrationSet
    isotropic_shielding_ppm: list[float] = Field(min_length=1, max_length=400)
    atom_symbols: list[str] | None = Field(default=None, max_length=400)

class IdentityCheck(CalibratedShifts):
    observed_shift_ppm: list[float] = Field(min_length=1, max_length=400)
    @model_validator(mode="after")
    def matched(self):
        if len(self.observed_shift_ppm) != len(self.isotropic_shielding_ppm):
            raise ValueError("Observed shifts must be explicitly matched one-to-one with computed shieldings")
        return self
