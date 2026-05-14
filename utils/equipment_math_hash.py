"""Hash matematici per sensori/datalogger/preamp (dedup NRL e indice locale)."""

from __future__ import annotations

import hashlib
import json

from core.models.base_models import Datalogger, Preamplifier, Sensor


def _format_sig(val):
    if val is None:
        return "0"
    return f"{float(val):.4g}"


def get_sensor_hash(s: Sensor) -> str:
    sens = _format_sig(s.sensitivity)
    freq = _format_sig(s.frequency)
    a0 = _format_sig(s.normalization_factor)
    pz_type = (s.pz_transfer_function_type or "").strip().upper()
    try:
        p_list = sorted([f"{_format_sig(p.real_val)},{_format_sig(p.imag_val)}" for p in s.poles])
        z_list = sorted([f"{_format_sig(z.real_val)},{_format_sig(z.imag_val)}" for z in s.zeros])
    except AttributeError:
        p_list = sorted([f"{_format_sig(p.real)},{_format_sig(p.imag)}" for p in s.poles])
        z_list = sorted([f"{_format_sig(z.real)},{_format_sig(z.imag)}" for z in s.zeros])
    pz_raw = f"{a0}_{pz_type}_P:{'|'.join(p_list)}_Z:{'|'.join(z_list)}"
    pz_hash = hashlib.sha256(pz_raw.encode()).hexdigest()[:8]
    return f"SENS_G_{sens}_PZ_{pz_hash}"


def get_datalogger_hash(d: Datalogger) -> str:
    gain = f"{float(d.gain or 0.0):.4f}"
    hw_d = f"{float(getattr(d, 'base_hardware_delay', 0.0) or 0.0):.4f}"
    f_hash = ""
    sorted_filters = sorted(d.filters, key=lambda x: getattr(x, "stage_number", 0))
    for i, f in enumerate(sorted_filters, 1):
        rate = f"{float(f.input_sample_rate or 0.0):.2f}"
        raw = getattr(f, "coefficients", "{}") or "{}"
        try:
            p = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(p, list):
                p = {"type": "FIR", "coefficients": p}
            t = p.get("type", "FIR")

            def _n(l):
                return "|".join([f"{float(v or 0.0):.6e}" for v in l])

            if t == "IIR":
                c = f"N:{_n(p.get('numerators', []))}D:{_n(p.get('denominators', []))}"
            elif t == "POLES":
                z = "|".join(
                    sorted([f"{float(v[0] or 0.0):.4f},{float(v[1] or 0.0):.4f}" for v in p.get("zeros", [])])
                )
                pp = "|".join(
                    sorted([f"{float(v[0] or 0.0):.4f},{float(v[1] or 0.0):.4f}" for v in p.get("poles", [])])
                )
                c = f"Z:{z}P:{pp}"
            else:
                c = f"C:{_n(p.get('coefficients', []))}"
            s_hash = hashlib.sha256(f"{t}_{f.decimation_factor}_{rate}_{c}".encode()).hexdigest()[:8]
            f_hash += f"S{i}_{s_hash}|"
        except Exception:
            f_hash += f"S{i}_ERR|"
    return f"G_{gain}_H_{hw_d}_F_{f_hash}"


def get_preamplifier_hash(p: Preamplifier) -> str:
    if not p:
        return "none"
    stages_data = []
    if hasattr(p, "analog_stages") and p.analog_stages:
        for stage in p.analog_stages:
            stages_data.append(
                {
                    "gain": float(stage.stage_gain),
                    "poles": sorted([(float(pz.real_val), float(pz.imag_val)) for pz in stage.poles]),
                    "zeros": sorted([(float(pz.real_val), float(pz.imag_val)) for pz in stage.zeros]),
                }
            )
    else:
        stages_data = [{"gain": 1.0, "poles": [], "zeros": []}]
    imprint = json.dumps(stages_data, sort_keys=True)
    return hashlib.sha256(imprint.encode()).hexdigest()
