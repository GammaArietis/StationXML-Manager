import os
import logging
import json
from obspy.clients.nrl import NRL
from core.models.base_models import Sensor, Datalogger, PoleZero, ResponseFilter
from obspy.core.inventory.response import (
    FIRResponseStage, CoefficientsTypeResponseStage,
    PolynomialResponseStage, PolesZerosResponseStage
)
import math

logger = logging.getLogger(__name__)

class NRLManager:
    def __init__(self):
        """Local NRL Initialization."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            nrl_path = os.path.join(current_dir, 'NRL_v2')
            self.nrl = NRL(root=nrl_path)
            logger.info("Local NRL (v2) successfully loaded.")
        except Exception as e:
            logger.exception("Unable to initialize NRL: %s", e)
            self.nrl = None

    def auto_classify_sensor_type(self, sensor):
        """
        Determines the sensor type (SM, VBB, BB, SP, etc.) based 
        exclusively on physical units and Laplace Poles.
        """
        unit_up = str(sensor.input_units or "").strip().upper()

        if "M/S**2" in unit_up: return "SM"
        if "PA" in unit_up: return "PRESSURE"
        if "RAD" in unit_up: return "TILTMETER"
        if "T" in unit_up or "TESLA" in unit_up: return "MAGNETOMETER"

        if "M/S" in unit_up and sensor.poles:
            valid_poles = []
            for p in sensor.poles:
                real_val = getattr(p, 'real_val', getattr(p, 'real', 0.0))
                imag_val = getattr(p, 'imag_val', getattr(p, 'imag', 0.0))
                magnitude = math.sqrt(real_val**2 + imag_val**2)
                if magnitude > 1e-6:
                    valid_poles.append(magnitude)

            if valid_poles:
                min_mag = min(valid_poles)
                is_hertz = "HERTZ" in str(sensor.pz_transfer_function_type or "").upper()
                fc = min_mag if is_hertz else (min_mag / (2 * math.pi))
                
                if fc <= 0.02:  return "VBB"
                elif fc <= 0.2: return "BB"
                elif fc >= 1.0: return "SP"
                else:           return "BB"

        return "SENSOR"

    def get_sensor_options(self, *keys):
        if not self.nrl: return []
        try:
            node = self.nrl.sensors
            for k in keys: node = node[k]
            return sorted(node.keys()) if isinstance(node, dict) else None
        except: return []

    def get_datalogger_options(self, *keys):
        if not self.nrl: return []
        try:
            node = self.nrl.dataloggers
            for k in keys: node = node[k]
            return sorted(node.keys()) if isinstance(node, dict) else None
        except: return []

    def fetch_sensor(self, keys):
        if not self.nrl: return None
        try:
            obspy_resp = self.nrl.get_sensor_response(keys)
            return self._convert_nrl_sensor(keys, obspy_resp)
        except Exception as e:
            logger.exception("Error downloading sensor from NRL: %s", e)
            return None

    def fetch_datalogger(self, keys):
        if not self.nrl: return None
        try:
            obspy_resp = self.nrl.get_datalogger_response(keys)
            return self._convert_nrl_datalogger(keys, obspy_resp)
        except Exception as e:
            logger.exception("Error downloading datalogger from NRL: %s", e)
            return None

    def _convert_nrl_sensor(self, keys, obspy_resp):
        """Converts Sensor (Fix PoleZero, Units and Transfer Function Type)."""
        mfg = str(keys[0]).upper() if keys else "UNKNOWN"
        model_base = str(keys[1]).upper() if len(keys) > 1 else "UNKNOWN"
        extra = " ".join([str(k) for k in keys[2:]]).upper()
        full_model = f"{model_base} ({extra})" if extra else model_base
        
        s_sens, s_freq, s_norm_f, s_norm_q = 1.0, 1.0, 1.0, 1.0
        paz_zeros, paz_poles = [], []
        in_u, out_u = "m/s", "V"
        pz_type = "LAPLACE (RADIANS/SECOND)" # Standard default value

        nrl_path_str = "->".join(keys)
        nrl_description = ""

        if obspy_resp and obspy_resp.response_stages:
            stage = obspy_resp.response_stages[0]
            
            nrl_description = getattr(stage, 'description', "")

            s_sens = getattr(stage, 'stage_gain', 1.0) or 1.0
            s_freq = getattr(stage, 'stage_gain_frequency', 1.0) or 1.0
            
            in_u = str(getattr(stage, 'input_units', "m/s") or "m/s").strip()
            out_u = str(getattr(stage, 'output_units', "V") or "V").strip()
            
            pz_type = getattr(stage, 'pz_transfer_function_type', pz_type)

            if hasattr(stage, 'zeros') and hasattr(stage, 'poles'):
                s_norm_f = getattr(stage, 'normalization_factor', 1.0) or 1.0
                s_norm_q = getattr(stage, 'normalization_frequency', 1.0) or 1.0
                paz_zeros = [PoleZero(z.real, z.imag) for z in (stage.zeros or [])]
                paz_poles = [PoleZero(p.real, p.imag) for p in (stage.poles or [])]

        if nrl_description:
            final_description = nrl_description.strip()
        else:
            final_description = "_".join([str(k).strip() for k in keys])

        temp_sensor = Sensor(
            manufacturer=mfg, model=full_model, type="SENSOR",
            description=final_description,
            nrl_path=nrl_path_str,
            sensitivity=s_sens, frequency=s_freq,
            normalization_factor=s_norm_f, normalization_freq=s_norm_q,
            input_units=in_u, output_units=out_u, pz_transfer_function_type=pz_type,
            zeros=paz_zeros, poles=paz_poles
        )
        
        # Use the calculation logic that is now centralized
        temp_sensor.type = self.auto_classify_sensor_type(temp_sensor)
        
        return temp_sensor
    
    def _convert_nrl_datalogger(self, keys, obspy_resp):
        mfg = str(keys[0]).upper() if keys else "UNKNOWN"
        model = f"{keys[1].upper()} ({' '.join(keys[2:]).upper()})" if len(keys) > 1 else "UNKNOWN"
        filters, gain, delay, corr = [], 1.0, 0.0, 0.0

        nrl_path_str = "->".join(keys)
        nrl_description = ""

        if obspy_resp and obspy_resp.response_stages:
            nrl_description = getattr(obspy_resp.response_stages[0], 'description', "")

            for s in obspy_resp.response_stages:
                iu = str(getattr(s, 'input_units', '') or '').strip().upper()
                ou = str(getattr(s, 'output_units', '') or '').strip().upper()
                
                payload = None
                
                if "COUNT" in ou and "COUNT" not in iu:
                    gain = getattr(s, 'stage_gain', 1.0) or 1.0
                    delay = getattr(s, 'decimation_delay', 0.0) or 0.0
                    corr = getattr(s, 'decimation_correction', 0.0) or 0.0
                    payload = {"type": "A/D"}
                
                elif isinstance(s, CoefficientsTypeResponseStage):
                    num = s.numerator if s.numerator is not None else []
                    den = s.denominator if s.denominator is not None else []
                    
                    if len(den) > 1 or (len(den) == 1 and den[0] != 1.0):
                        payload = {"type": "IIR", "numerators": [float(c) for c in num], "denominators": [float(c) for c in den]}
                    else:
                        payload = {"type": "FIR", "coefficients": [float(c) for c in num]}
                
                elif isinstance(s, FIRResponseStage):
                    coeffs = s.coefficients if s.coefficients is not None else []
                    payload = {"type": "FIR", "coefficients": [float(c) for c in coeffs]}
                
                elif isinstance(s, PolesZerosResponseStage):
                    payload = {
                        "type": "POLES",
                        "a0": getattr(s, 'normalization_factor', 1.0) or 1.0,
                        "zeros": [[z.real, z.imag] for z in (s.zeros or [])],
                        "poles": [[p.real, p.imag] for p in (s.poles or [])]
                    }
                
                else:
                    c = getattr(s, 'coefficients', None) or getattr(s, 'numerator', None)
                    if c is not None and not isinstance(c, str):
                        payload = {"type": "FIR", "coefficients": [float(val) for val in c]}

                if payload:
                    payload["input_units"] = iu
                    payload["output_units"] = ou
                    payload["stage_gain"] = getattr(s, 'stage_gain', 1.0) or 1.0
                    payload["stage_gain_frequency"] = getattr(s, 'stage_gain_frequency', 0.0) or 0.0
                    
                    s_delay = getattr(s, 'decimation_delay', 0.0) or 0.0
                    s_corr = getattr(s, 'decimation_correction', 0.0) or 0.0
                    
                    filters.append(ResponseFilter(
                        stage_number=s.stage_sequence_number, filter_type=payload["type"],
                        coefficients=json.dumps(payload, sort_keys=True, separators=(',', ':')),
                        decimation_factor=getattr(s, 'decimation_factor', 1) or 1,
                        input_sample_rate=getattr(s, 'decimation_input_sample_rate', 0.0) or 0.0,
                        output_sample_rate=getattr(s, 'decimation_output_sample_rate', 0.0) or 0.0,
                        estimated_delay=s_delay,            # <--- ADDED
                        correction_applied=s_corr
                    ))
                    
        # --- FIX: If empty, builds the joined string with underscores ---
        if nrl_description:
            final_description = nrl_description.strip()
        else:
            final_description = "_".join([str(k).strip() for k in keys])

        return Datalogger(
            manufacturer=mfg, model=model,
            description=final_description,          # <--- TRUE DESC. or "Brand_Model_Etc"
            nrl_path=nrl_path_str,
            gain=gain, base_hardware_delay=delay, base_hardware_correction=corr, filters=filters
        )
        
    def extract_stage_coefficients(stage):
        """
        Extracts coefficients from an ObsPy ResponseStage 
        and formats them for saving in SQLite (JSON).
        """
        coeff_data = []

        # 1. FIR Filters (Finite Impulse Response)
        if hasattr(stage, 'coefficients') and stage.coefficients:
            coeff_data = list(stage.coefficients)
        elif hasattr(stage, 'numerators') and stage.numerators and not hasattr(stage, 'denominators'):
            coeff_data = list(stage.numerators)
            
        # 2. IIR Filters (Infinite Impulse Response) - Have both numerators and denominators
        elif hasattr(stage, 'numerators') and hasattr(stage, 'denominators'):
            if stage.numerators or stage.denominators:
                coeff_data = {
                    "numerators": list(stage.numerators) if stage.numerators else [],
                    "denominators": list(stage.denominators) if stage.denominators else []
                }

        # Return serialized JSON (pure list for FIR, dictionary for IIR)
        return json.dumps(coeff_data)
        
    def suggest_best_match(self, description: str, equip_type: str):
        """Searches for the best match in the local cache for the traffic light."""
        import json, os, re
        
        cache_path = "data/nrl_math_cache.json"
        if not os.path.exists(cache_path) or not description:
            return None

        with open(cache_path, 'r', encoding='utf-8') as f:
            cache = json.load(f)
            
        group = cache.get('sensors' if equip_type == 'sensor' else 'dataloggers', {})
        stopwords = {"SENSOR", "SENS", "INGV", "VEL", "ACC", "XYZ", "MODEL", "DATALOGGER", "LOGGER", "ACQ", "NONE"}
        
        query_words = {w for w in re.findall(r'\w+', description.upper()) if len(w) > 1 and w not in stopwords}
        if not query_words: return None

        best_path = None
        max_overlap = 0

        for n_hash, n_names in group.items():
            for full_name in n_names:
                nrl_words = {w for w in re.findall(r'\w+', full_name.upper()) if len(w) > 1 and w not in stopwords}
                overlap = len(query_words & nrl_words)
                
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_path = full_name

        if best_path and max_overlap > 0:
            parts = [p.strip() for p in best_path.split("->")]
            display_name = f"{parts[0]} {parts[1]}" if len(parts) > 1 else parts[0]
            return {"keys": parts, "display_name": display_name, "score": max_overlap}
            
        return None
        
    def try_reconstruct_nrl_path(self, description: str, equip_type: str):
        """
        Tenta di recuperare l'nrl_path originale se la descrizione è unita da underscore.
        Es: 'Nanometrics_Titan_2g' -> 'Nanometrics->Titan->2g'
        """
        if not description or "_" not in description:
            return None
            
        # Separiamo la descrizione usando l'underscore
        keys = [k.strip() for k in description.split("_") if k.strip()]
        if not self.nrl or not keys:
            return None
            
        try:
            # Scegliamo la radice dell'albero NRL giusto
            node = self.nrl.sensors if equip_type.upper() == "SENSOR" else self.nrl.dataloggers
            
            # Navighiamo l'albero cartella per cartella
            for k in keys:
                if k in node:
                    node = node[k]
                else:
                    return None # Il percorso si è interrotto, non è un NRL valido
                
            # Se siamo arrivati alla fine e non ci sono più sottocartelle (non è un dict),
            # significa che abbiamo trovato la "foglia" (il file RESP)!
            if not isinstance(node, dict):
                return "->".join(keys)
                
            return None
        except Exception:
            return None
