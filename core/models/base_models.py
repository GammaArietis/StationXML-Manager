from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


def coerce_fdsn_restricted_status(value: object) -> str:
    """FDSN StationXML often leaves restrictedStatus unset (ObsPy exposes None)."""
    if value is None:
        return "open"
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else "open"
    return str(value).strip() or "open"


class ResponseFilter(BaseModel):
    """Model for individual filtering stages (FIR/Coefficients) of the Datalogger."""
    stage_number: int
    filter_type: str              # 'FIR' or 'COEFFICIENTS'
    coefficients: str             # JSON string with the array of numerators
    decimation_factor: int = 1
    input_sample_rate: float = 0.0
    output_sample_rate: float = 0.0
    estimated_delay: float = 0.0      # <--- ENSURE THIS IS PRESENT
    correction_applied: float = 0.0   # <--- ENSURE THIS IS PRESENT
    id: Optional[int] = None


class Operator(BaseModel):
    """Model for the Operators/Agencies Catalog."""
    id: Optional[int] = None
    agency: str = ""
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    website: Optional[str] = None
    phone_country_code: Optional[int] = 39     # <--- NEW
    phone_area_code: Optional[int] = 0         # <--- NEW
    phone_number: Optional[str] = None         # <--- NEW (the actual number)


class Network(BaseModel):
    """Model for the Seismic Network."""
    id: Optional[int] = None
    code: str = ""
    description: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    doi: Optional[str] = None
    operator_id: Optional[int] = None
    restricted_status: str = "open"
    comments: Optional[str] = None

    @field_validator("restricted_status", mode="before")
    @classmethod
    def _normalize_restricted_status(cls, v: object) -> str:
        return coerce_fdsn_restricted_status(v)


class Station(BaseModel):
    """Model for the Station."""
    id: Optional[int] = None
    network_id: Optional[int] = None
    code: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    elevation: float = 0.0
    site_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    creation_date: Optional[str] = None
    operator_id: Optional[int] = None
    vault: Optional[str] = None     # <--- ADDED
    geology: Optional[str] = None   # <--- ADDED
    restricted_status: str = "open"
    water_level: Optional[float] = None
    description: Optional[str] = None  # Extended site description
    town: Optional[str] = None         # City/Town
    county: Optional[str] = None       # County/Province (e.g., PA)
    region: Optional[str] = None       # Region (e.g., Sicily)
    country: Optional[str] = None      # Country (e.g., Italy)
    comments: Optional[str] = None

    @field_validator("restricted_status", mode="before")
    @classmethod
    def _normalize_restricted_status(cls, v: object) -> str:
        return coerce_fdsn_restricted_status(v)


class PoleZero(BaseModel):
    """Modello per Poli e Zeri - Compatibile con DAO e con il vecchio stile NRL."""
    model_config = ConfigDict(populate_by_name=True)
    
    id: Optional[int] = None
    real_val: float = Field(default=0.0, alias="real")
    imag_val: float = Field(default=0.0, alias="imag")
    real_error: Optional[float] = None
    imag_error: Optional[float] = None

    # FIX CRITICO: Permette la chiamata PoleZero(real, imag) usata in nrl_client.py
    def __init__(self, real: float = 0.0, imag: float = 0.0, **data):
        # Se vengono passati argomenti posizionali, li mappiamo sui campi giusti
        if 'real_val' not in data and 'real' not in data:
            data['real_val'] = real
        if 'imag_val' not in data and 'imag' not in data:
            data['imag_val'] = imag
        super().__init__(**data)


class Sensor(BaseModel):
    """Modello Sensore - Struttura piatta per compatibilità totale con equipment_dao.py."""
    # Campi base riportati qui per non rompere il DAO (righe 95, 120, 145)
    id: Optional[int] = None
    manufacturer: str = ""
    model: str = ""
    
    type: Optional[str] = "SENSOR"
    description: Optional[str] = None
    sensitivity: Optional[float] = 0.0
    frequency: Optional[float] = 1.0
    normalization_factor: Optional[float] = None  # A0
    normalization_freq: Optional[float] = None    # Norm. frequency
    input_units: str = "m/s"
    output_units: str = "V"
    pz_transfer_function_type: str = "LAPLACE (RADIANS/SECOND)"
    zeros: List[PoleZero] = Field(default_factory=list)
    poles: List[PoleZero] = Field(default_factory=list)
    nrl_path: Optional[str] = None

    # FIX: Gestione maiuscole PZ Type
    @field_validator('pz_transfer_function_type', mode='before')
    @classmethod
    def uppercase_pz_type(cls, v):
        if v: return str(v).upper()
        return "LAPLACE (RADIANS/SECOND)"

    # FIX: Gestione stringhe "None" da AROL/NRL per tutti i campi numerici
    @field_validator('normalization_factor', 'normalization_freq', 'sensitivity', 'frequency', mode='before')
    @classmethod
    def parse_none_string(cls, v):
        if isinstance(v, str) and v.lower() in ("none", "null", ""):
            return None
        return v


class Equipment(BaseModel):
    """Rimane per Datalogger e logica generale."""
    id: Optional[int] = None
    manufacturer: str = ""
    model: str = ""


class Datalogger(BaseModel):
    """Model for the Datalogger (Registry + Filter chain)."""
    model_config = ConfigDict(from_attributes=True) # Mantiene la compatibilità con i DAO
    
    id: Optional[int] = None
    manufacturer: str = ""
    model: str = ""
    description: Optional[str] = None
    gain: Optional[float] = None
    max_clock_drift: Optional[float] = None
    base_hardware_delay: float = 0.0
    base_hardware_correction: float = 0.0
    filters: List[ResponseFilter] = Field(default_factory=list)
    nrl_path: Optional[str] = None

    # --- IL METODO MIGLIORE ---
    @field_validator('filters', mode='before')
    @classmethod
    def sanitize_filters(cls, v):
        """
        Se riceve una lista di oggetti (magari caricati da moduli diversi),
        li trasforma in dizionari prima della validazione reale.
        """
        if isinstance(v, list):
            # Se l'elemento è un oggetto Pydantic, estraiamo i dati
            return [f.model_dump() if hasattr(f, 'model_dump') else f for f in v]
        return v


class ResponseFilter(BaseModel):
    """Stadio di filtraggio datalogger."""
    id: Optional[int] = None
    stage_number: int = 1
    filter_type: str = "FIR"
    input_sample_rate: Optional[float] = None
    output_sample_rate: Optional[float] = None
    decimation_factor: Optional[int] = 1
    gain: Optional[float] = 1.0
    estimated_delay: Optional[float] = 0.0
    correction_applied: Optional[float] = 0.0
    description: Optional[str] = None
    coefficients: str = "[]"


class Channel(BaseModel):
    """Model for the Channel (Specific installation)."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    station_id: Optional[int] = None
    code: str = ""
    location_code: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    elevation: Optional[float] = None
    depth: Optional[float] = 0.0  # Rreso Optional
    azimuth: Optional[float] = None
    dip: Optional[float] = None
    sample_rate: Optional[float] = 100.0 # Reso Optional
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    sensor_id: Optional[int] = None
    datalogger_id: Optional[int] = None
    overall_sensitivity: Optional[float] = None
    sensor_serial_number: Optional[str] = None
    datalogger_serial_number: Optional[str] = None
    types: str = "CONTINUOUS,GEOPHYSICAL"
    restricted_status: str = "open"
    clock_drift: Optional[float] = 0.0 # <--- FIX: Reso Optional
    calibration_units: Optional[str] = None
    pre_amplifier_id: Optional[int] = None
    pre_amplifier_serial_number: Optional[str] = None
    pre_amplifier_gain: Optional[float] = 1.0
    stage_gain_delay: float = 0.0
    stage_gain_correction: float = 0.0
    comments: Optional[str] = None

    @field_validator("restricted_status", mode="before")
    @classmethod
    def _normalize_channel_restricted_status(cls, v: object) -> str:
        return coerce_fdsn_restricted_status(v)

    # Applichiamo lo stesso validatore usato in Sensor per gestire i None e le stringhe "None"
    @field_validator('clock_drift', 'sample_rate', 'depth', 'pre_amplifier_gain', mode='before')
    @classmethod
    def parse_none_values(cls, v):
        if v is None:
            return 0.0
        if isinstance(v, str) and v.lower() in ("none", "null", ""):
            return 0.0
        return v


class AnalogStage(BaseModel):
    """Model for a single analog stage within a preamplifier."""
    stage_sequence: int
    stage_gain: float = 1.0
    input_units: str = "V"
    output_units: str = "V"
    name: str = ""
    poles: List[PoleZero] = Field(default_factory=list)
    zeros: List[PoleZero] = Field(default_factory=list)
    id: Optional[int] = None


class Preamplifier(BaseModel):
    """Model for the Preamplifier Catalog (Signal Conditioning)."""
    id: Optional[int] = None
    manufacturer: str = ""
    model: str = ""
    description: Optional[str] = None
    # Removed single poles and zeros, now using a list of stages!
    analog_stages: List[AnalogStage] = Field(default_factory=list)
