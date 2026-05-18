import io
import json
import logging
import zipfile
from typing import Callable, List, Optional, Set, Tuple

from obspy.core.inventory import Inventory, Network, Station, Channel, Site, Equipment
from obspy.core.inventory.response import (
    Response, PolesZerosResponseStage, InstrumentSensitivity,
    ResponseStage, FIRResponseStage, CoefficientsTypeResponseStage,
    PolynomialResponseStage
)
from obspy.core.inventory.util import Operator, Person, PhoneNumber
from obspy import UTCDateTime
from obspy.core.inventory import Comment

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int, str], None]]
CancelCallback = Optional[Callable[[], bool]]


class StationXMLExporter:
    def __init__(self, net_ctrl, sta_ctrl, cha_ctrl, eq_ctrl):
        self.net_ctrl = net_ctrl
        self.sta_ctrl = sta_ctrl
        self.cha_ctrl = cha_ctrl
        self.eq_ctrl = eq_ctrl
        
        # --- FIX 2: Creation of the warnings collector ---
        self.validation_warnings = set()

    @staticmethod
    def _emit_export_progress(
        callback: ProgressCallback,
        current: int,
        total: int,
        message: str,
    ) -> None:
        if not callback:
            return
        try:
            callback(current, total, message)
        except Exception as exc:
            logger.warning("export progress_callback failed: %s", exc)

    def _iter_export_networks(self, target_station_id: Optional[int]):
        for net in self.net_ctrl.get_all_networks():
            stations = self.sta_ctrl.get_stations_by_network(net.id)
            if target_station_id is not None:
                stations = [s for s in stations if s.id == target_station_id]
            if not stations:
                continue
            yield net, stations

    def _count_export_units(self, target_station_id: Optional[int]) -> Tuple[int, int, int]:
        nn = ns = nc = 0
        for _net, stations in self._iter_export_networks(target_station_id):
            nn += 1
            for sta in stations:
                ns += 1
                nc += len(self.cha_ctrl.get_channels_by_station(sta.id))
        return nn, ns, nc
        
    def _build_fdsn_comments(self, comments_json: str) -> list:
        """Reads the JSON string from the database and recreates ObsPy Comment objects."""
        fdsn_comments = []
        if not comments_json:
            return fdsn_comments
            
        try:
            c_list = json.loads(comments_json)
            for c_dict in c_list:
                val = str(c_dict.get("value", "")).strip()
                if not val: continue
                
                comment = Comment(value=val)
                
                if c_dict.get("begin_date"):
                    comment.begin_date = UTCDateTime(c_dict["begin_date"])
                if c_dict.get("end_date"):
                    comment.end_date = UTCDateTime(c_dict["end_date"])
                if c_dict.get("subject"):
                    comment.subject = c_dict["subject"]
                
                a_name = c_dict.get("author_name")
                a_ag = c_dict.get("author_agency")
                if a_name or a_ag:
                    author = Person()
                    if a_name: author.names = [a_name]
                    if a_ag: author.agency = a_ag
                    comment.authors = [author]
                    
                fdsn_comments.append(comment)
        except Exception as e:
            # Safety fallback: if the text is not JSON, we put it as a raw string
            fdsn_comments.append(Comment(value=str(comments_json)))
            
        return fdsn_comments

    # --- FIX 1: No @staticmethod and added 'self' in parenthesis ---
    def _sanitize_fdsn_unit(self, raw_unit: str) -> str:
        """
        Converts units of measure into strict FDSN StationXML format (Case-sensitive).
        """
        if not raw_unit:
            return "UNKNOWN"
            
        unit = raw_unit.strip().lower()
        
        # Exact FDSN mapping: SI in lowercase, others specific in uppercase
        unit_map = {
            "m/s": "m/s", "m/sec": "m/s", "metri/secondo": "m/s",
            "m/s^2": "m/s**2", "m/s**2": "m/s**2", "m/sec2": "m/s**2", "cm/s**2": "cm/s**2",
            "m": "m", "metri": "m",
            "v": "V", "volt": "V", "volts": "V",
            "a": "A", "ampere": "A",
            
            # --- THE FIX IS HERE: ALL LOWERCASE ("counts") ---
            "counts": "counts", "count": "counts", "c": "counts", "digit": "counts",
            
            "rad/s": "rad/s", "rad/sec": "rad/s", "hertz": "Hz", "hz": "Hz"
        }
        
        # If it's not in the map, we register it in warnings
        if unit not in unit_map:
            self.validation_warnings.add(raw_unit.strip())
            
        # Return exact value from map, otherwise the raw value (without forcing upper!)
        return unit_map.get(unit, raw_unit.strip())

    def _parse_date(self, date_str: str):
        if date_str:
            try:
                return UTCDateTime(date_str)
            except Exception as e:
                logger.warning(f"Invalid date format {date_str}: {e}")
        return None

    def _build_operator(self, operator_id: int, operators_db: dict):
        if not operator_id or operator_id not in operators_db:
            return []
            
        db_op = operators_db[operator_id]
        obspy_op = Operator(
            agency=db_op.agency,
            website=str(db_op.website).strip() if db_op.website else None
        )
        
        from utils.fdsn_phone import sanitize_fdsn_phone_string

        fdsn_phone = None
        if db_op.phone_number:
            fdsn_phone = sanitize_fdsn_phone_string(
                db_op.phone_number,
                default_country_code=db_op.phone_country_code
                if db_op.phone_country_code is not None
                else 39,
            )

        if db_op.contact_name or db_op.contact_email or fdsn_phone:
            person = Person(
                names=[db_op.contact_name] if db_op.contact_name else [],
                emails=[db_op.contact_email] if db_op.contact_email else [],
            )
            if fdsn_phone:
                country_code_str, _subscriber = fdsn_phone.split("-", 1)
                person.phones = [
                    PhoneNumber(
                        country_code=int(country_code_str),
                        area_code=db_op.phone_area_code
                        if db_op.phone_area_code is not None
                        else 0,
                        phone_number=fdsn_phone,
                    )
                ]

            obspy_op.contacts = [person]
            
        return [obspy_op]

    def build_inventory(
        self,
        target_station_id: Optional[int] = None,
        *,
        output_path: Optional[str] = None,
        validate: bool = True,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ) -> Optional[Inventory]:
        if target_station_id is None:
            raise ValueError(
                "Global inventory export is no longer supported. "
                "Use build_station_inventory(station_id) for per-station StationXML."
            )
        inv = Inventory(networks=[], source="StationXML Manager FDSN")

        sensors_db = {s.id: s for s in self.eq_ctrl.get_all_sensors()}
        dataloggers_db = {d.id: d for d in self.eq_ctrl.get_all_dataloggers()}
        operators_db = {op.id: op for op in self.eq_ctrl.get_all_operators()}

        nn, ns, nc = self._count_export_units(target_station_id)
        total = nn + ns + nc + 2
        cur = 0
        self._emit_export_progress(progress_callback, cur, total, "Preparing export…")
        if cancel_callback and cancel_callback():
            return None
        cur = 1
        self._emit_export_progress(
            progress_callback, cur, total, "Loading equipment & operator catalogs…"
        )
        if cancel_callback and cancel_callback():
            return None

        for net, stations in self._iter_export_networks(target_station_id):
            if cancel_callback and cancel_callback():
                return None
            cur += 1
            self._emit_export_progress(
                progress_callback, cur, total, f"Network {net.code}…"
            )

            net_identifiers = []
            if hasattr(net, 'doi') and net.doi:
                # ObsPy will automatically map this format to <Identifier type="DOI">
                net_identifiers.append(f"{net.doi}")

            obspy_net = Network(
                code=net.code,
                description=net.description,
                start_date=self._parse_date(net.start_date),
                end_date=self._parse_date(net.end_date),
                operators=self._build_operator(net.operator_id, operators_db),
                restricted_status=getattr(net, 'restricted_status', None) or 'open', # <--- MODIFIED HERE
                identifiers=net_identifiers
            )
            obspy_net.comments = self._build_fdsn_comments(getattr(net, 'comments', None))
            
            for sta in stations:
                if cancel_callback and cancel_callback():
                    return None
                cur += 1
                self._emit_export_progress(
                    progress_callback, cur, total, f"Station {sta.code}…"
                )

                site_obj = Site(
                    name=sta.site_name if sta.site_name else "Unknown",
                    description=getattr(sta, 'description', None),
                    town=getattr(sta, 'town', None),
                    county=getattr(sta, 'county', None),
                    region=getattr(sta, 'region', None),
                    country=getattr(sta, 'country', None)
                )

                obspy_sta = Station(
                    code=sta.code,
                    latitude=sta.latitude,
                    longitude=sta.longitude,
                    elevation=sta.elevation,
                    vault=getattr(sta, 'vault', None),
                    geology=getattr(sta, 'geology', None),
                    site=site_obj,
                    start_date=self._parse_date(sta.start_date),
                    end_date=self._parse_date(sta.end_date),
                    operators=self._build_operator(sta.operator_id, operators_db),
                    restricted_status=getattr(sta, 'restricted_status', None) or 'open', # <--- MODIFIED HERE
                    water_level=getattr(sta, 'water_level', None)
                )
                obspy_sta.comments = self._build_fdsn_comments(getattr(sta, 'comments', None))
                
                if hasattr(net, 'doi') and net.doi:
                    obspy_net.doi = net.doi

                channels = self.cha_ctrl.get_channels_by_station(sta.id)
                for cha in channels:
                    if cancel_callback and cancel_callback():
                        return None
                    cur += 1
                    loc = cha.location_code or "--"
                    self._emit_export_progress(
                        progress_callback,
                        cur,
                        total,
                        f"Channel {sta.code}.{cha.code} ({loc})…",
                    )

                    lat = cha.latitude if cha.latitude is not None else sta.latitude
                    lon = cha.longitude if cha.longitude is not None else sta.longitude
                    elev = cha.elevation if cha.elevation is not None else sta.elevation
                    
                    obspy_equip_sensor = None
                    obspy_response = None
                    obspy_equip_preamp = None
                    
                    sensor = sensors_db.get(cha.sensor_id) if cha.sensor_id else None
                    datalogger = dataloggers_db.get(cha.datalogger_id) if cha.datalogger_id else None
                    
                    # 1A. Retrieve Preamplifier Catalog
                    preamp_model = None
                    pa_id = getattr(cha, 'pre_amplifier_id', None)
                    if pa_id:
                        preamp_model = self.eq_ctrl.get_preamplifier_by_id(pa_id)
                    
                    preamp_gain = getattr(cha, 'pre_amplifier_gain', 1.0) or 1.0
                    preamp_sn = getattr(cha, 'pre_amplifier_serial_number', None)
                    
                    # 1B. SENSOR AND PREAMP EQUIPMENT
                    if sensor:
                        obspy_equip_sensor = Equipment(
                            type=sensor.type or "SENSOR",
                            manufacturer=sensor.manufacturer,
                            model=sensor.model,
                            description=sensor.description,
                            serial_number=str(cha.sensor_serial_number) if cha.sensor_serial_number else None
                        )
                        
                    if preamp_model or preamp_sn:
                        obspy_equip_preamp = Equipment(
                            type="PRE-AMPLIFIER",
                            manufacturer=getattr(preamp_model, 'manufacturer', None) if preamp_model else None,
                            model=getattr(preamp_model, 'model', None) if preamp_model else None,
                            description=getattr(preamp_model, 'description', None) if preamp_model else None,
                            serial_number=str(preamp_sn) if preamp_sn else None
                        )
                        
                    # 2. INSTRUMENTAL RESPONSE
                    if sensor and getattr(sensor, 'sensitivity', None) is not None:
                        try:
                            stages = []
                            a0_val = getattr(sensor, 'normalization_factor', 1.0) or 1.0
                            norm_freq = getattr(sensor, 'normalization_freq', 1.0) or 1.0
                            
                            # --- THE FIX IS HERE: We extract the correct Gain frequency (e.g. 0.2 Hz) ---
                            gain_freq = getattr(sensor, 'frequency', 1.0) or 1.0
                            
                            # === SANITIZE UNITS OF MEASURE ===
                            safe_in_units = self._sanitize_fdsn_unit(sensor.input_units) if sensor.input_units else "M/S"
                            safe_out_units = self._sanitize_fdsn_unit(sensor.output_units) if sensor.output_units else "V"
                            
                            # STAGE 1: Sensor (Poles and Zeros)
                            pz_stage = PolesZerosResponseStage(
                                stage_sequence_number=1,
                                stage_gain=sensor.sensitivity,
                                stage_gain_frequency=gain_freq, # <-- We use gain_freq!
                                input_units=safe_in_units,
                                output_units=safe_out_units,
                                pz_transfer_function_type=getattr(sensor, 'pz_transfer_function_type', 'LAPLACE (RADIANS/SECOND)').upper(),
                                normalization_factor=a0_val,
                                normalization_frequency=norm_freq, # This stays norm_freq
                                zeros=[complex(z.real_val, z.imag_val) for z in getattr(sensor, 'zeros', [])],
                                poles=[complex(p.real_val, p.imag_val) for p in getattr(sensor, 'poles', [])]
                            )
                            stages.append(pz_stage)
                            
                            # Calculate accumulated sensitivity (We start from the sensor)
                            total_sensitivity_value = sensor.sensitivity
                            final_output_units = safe_out_units
                            
                            # INTERMEDIATE STAGE: Pre-Amplifier / Analog Filters (MULTI-STAGE)
                            if preamp_model and hasattr(preamp_model, 'analog_stages') and preamp_model.analog_stages:
                                for a_stage in preamp_model.analog_stages:
                                    pa_zeros = [complex(z.real_val, z.imag_val) for z in a_stage.zeros] if a_stage.zeros else []
                                    pa_poles = [complex(p.real_val, p.imag_val) for p in a_stage.poles] if a_stage.poles else []
                                    
                                    preamp_stage = PolesZerosResponseStage(
                                        stage_sequence_number=a_stage.stage_sequence,
                                        stage_gain=a_stage.stage_gain,
                                        stage_gain_frequency=gain_freq, # <-- We use gain_freq!
                                        input_units=self._sanitize_fdsn_unit(a_stage.input_units),
                                        output_units=self._sanitize_fdsn_unit(a_stage.output_units),
                                        pz_transfer_function_type="LAPLACE (RADIANS/SECOND)",
                                        normalization_factor=1.0,
                                        normalization_frequency=norm_freq,
                                        zeros=pa_zeros,
                                        poles=pa_poles,
                                        name=a_stage.name if hasattr(a_stage, 'name') and a_stage.name else None
                                    )
                                    stages.append(preamp_stage)
                                    total_sensitivity_value *= a_stage.stage_gain
                                    final_output_units = self._sanitize_fdsn_unit(a_stage.output_units)
                                    
                            elif preamp_gain != 1.0:
                                # Safety fallback for old channels
                                preamp_stage = PolesZerosResponseStage(
                                    stage_sequence_number=len(stages) + 1,
                                    stage_gain=preamp_gain,
                                    stage_gain_frequency=gain_freq, # <-- We use gain_freq!
                                    input_units=safe_out_units,
                                    output_units="V",
                                    pz_transfer_function_type="LAPLACE (RADIANS/SECOND)",
                                    normalization_factor=1.0,
                                    normalization_frequency=norm_freq,
                                    zeros=[],
                                    poles=[]
                                )
                                stages.append(preamp_stage)
                                total_sensitivity_value *= preamp_gain
                                final_output_units = "V"

                            # SUBSEQUENT STAGES: Datalogger
                            if datalogger:

                                if hasattr(datalogger, 'filters') and datalogger.filters:
                                    
                                    # 1. Preliminary analysis of the chain
                                    current_rate = None
                                    for idx, f in enumerate(datalogger.filters):
                                        if f.input_sample_rate and f.input_sample_rate > 0:
                                            current_rate = f.input_sample_rate
                                            break
                                    
                                    if not current_rate:
                                        current_rate = cha.sample_rate * 1000 if cha.sample_rate else 1000.0
                                    
                                    raw_sens = getattr(cha, 'overall_sensitivity', None)
                                    try:
                                        safe_overall_sens = float(raw_sens) if raw_sens else None
                                        if safe_overall_sens is not None and safe_overall_sens <= 0.0:
                                            safe_overall_sens = None
                                    except Exception:
                                        safe_overall_sens = None
                                        
                                    sorted_filters = sorted(datalogger.filters, key=lambda x: getattr(x, 'stage_number', 0))

                                    for i, f in enumerate(sorted_filters):
                                        if not f.coefficients: continue
                                        
                                        try:
                                            payload = json.loads(f.coefficients)
                                            if isinstance(payload, list):
                                                payload = {"type": "FIR", "coefficients": payload}
                                        except Exception:
                                            continue
                                            
                                        f_type = payload.get("type", "FIR")
                                        s_in_units = self._sanitize_fdsn_unit(payload.get("input_units", "COUNTS"))
                                        s_out_units = self._sanitize_fdsn_unit(payload.get("output_units", "COUNTS"))
                                        s_gain = payload.get("stage_gain", 1.0)
                                        s_gain_freq = payload.get("stage_gain_frequency", 0.0)
                                        if s_gain_freq is None: s_gain_freq = 0.0

                                        nyquist = (cha.sample_rate / 2.0) if cha.sample_rate else None
                                        if nyquist and s_gain_freq > nyquist:
                                            s_gain_freq = nyquist
                                        
                                        is_last = (i == len(sorted_filters) - 1)
                                        target_rate = cha.sample_rate if cha.sample_rate else 1.0
                                        
                                        if is_last:
                                            calc_factor = int(round(current_rate / target_rate)) if current_rate >= target_rate else 1
                                            out_rate = target_rate
                                        else:
                                            calc_factor = getattr(f, 'decimation_factor', 1) or 1
                                            if calc_factor < 1: calc_factor = 1
                                            out_rate = current_rate / calc_factor
                                            
                                        if f_type == "A/D" and total_sensitivity_value > 0 and safe_overall_sens:
                                            expected_ad_gain = safe_overall_sens / total_sensitivity_value
                                            if abs(expected_ad_gain - s_gain) > (s_gain * 10):
                                                s_gain = expected_ad_gain
                                                
                                        if f_type in ["A/D", "DECIMATION"]:
                                            stage = CoefficientsTypeResponseStage(
                                                stage_sequence_number=len(stages) + 1, stage_gain=s_gain, stage_gain_frequency=s_gain_freq,
                                                input_units=s_in_units, output_units=s_out_units, cf_transfer_function_type="DIGITAL",
                                                numerator=[], denominator=[],
                                                decimation_input_sample_rate=current_rate, decimation_factor=calc_factor,
                                                decimation_delay=f.estimated_delay or 0.0, decimation_correction=f.correction_applied or 0.0, decimation_offset=0
                                            )
                                        elif f_type == "IIR":
                                            stage = CoefficientsTypeResponseStage(
                                                stage_sequence_number=len(stages) + 1, stage_gain=s_gain, stage_gain_frequency=s_gain_freq,
                                                input_units=s_in_units, output_units=s_out_units, cf_transfer_function_type="DIGITAL",
                                                numerator=payload.get('numerators', []), denominator=payload.get('denominators', []),
                                                decimation_input_sample_rate=current_rate, decimation_factor=calc_factor,
                                                decimation_delay=f.estimated_delay or 0.0, decimation_correction=f.correction_applied or 0.0, decimation_offset=0
                                            )
                                        elif f_type == "POLY":
                                            stage = PolynomialResponseStage(
                                                stage_sequence_number=len(stages) + 1, stage_gain=s_gain, stage_gain_frequency=s_gain_freq,
                                                input_units=s_in_units, output_units=s_out_units, pz_transfer_function_type="LAPLACE (RADIANS/SECOND)",
                                                approximation_type="MACLAURIN", frequency_lower_bound=0.0,
                                                frequency_upper_bound=(current_rate / 2) if current_rate else 100.0,
                                                approximation_lower_bound=0.0, approximation_upper_bound=1.0, maximum_error=0.0,
                                                coefficients=payload.get('coefficients', [])
                                            )
                                        elif f_type == "POLES":
                                            stage = PolesZerosResponseStage(
                                                stage_sequence_number=len(stages) + 1, stage_gain=s_gain, stage_gain_frequency=s_gain_freq,
                                                input_units=s_in_units, output_units=s_out_units, pz_transfer_function_type="LAPLACE (RADIANS/SECOND)",
                                                normalization_factor=payload.get('a0', 1.0), normalization_frequency=0.0,
                                                zeros=[complex(z[0], z[1]) for z in payload.get('zeros', [])],
                                                poles=[complex(p[0], p[1]) for p in payload.get('poles', [])]
                                            )
                                        else: # FIR
                                            stage = FIRResponseStage(
                                                stage_sequence_number=len(stages) + 1, stage_gain=s_gain, stage_gain_frequency=s_gain_freq,
                                                input_units=s_in_units, output_units=s_out_units, symmetry="NONE",
                                                coefficients=payload.get('coefficients', []),
                                                decimation_input_sample_rate=current_rate, decimation_factor=calc_factor,
                                                decimation_delay=f.estimated_delay or 0.0, decimation_correction=f.correction_applied or 0.0, decimation_offset=0
                                            )
                                        
                                        stages.append(stage)
                                        total_sensitivity_value *= s_gain
                                        current_rate = out_rate
                                        final_output_units = s_out_units
                            
                            final_sens_value = safe_overall_sens if safe_overall_sens is not None else total_sensitivity_value
                            
                            # --- FIX Nyquist Capper on the Correct Frequency ---
                            nyquist = (cha.sample_rate / 2.0) if cha.sample_rate else None
                            if nyquist and gain_freq > nyquist:
                                gain_freq = nyquist

                            sensitivity_obj = InstrumentSensitivity(
                                value=final_sens_value,
                                frequency=gain_freq,  # <-- We use gain_freq here!
                                input_units=safe_in_units,
                                output_units=final_output_units
                            )
                            
                            obspy_response = Response(
                                instrument_sensitivity=sensitivity_obj,
                                response_stages=stages
                            )
                        except Exception as e:
                            logger.error(f"Error generating Response for channel {cha.code}: {e}")
                    
                    # 3. DATALOGGER EQUIPMENT
                    obspy_equip_datalogger = None
                    if datalogger:
                        dl_desc = datalogger.description or ""
                           
                        obspy_equip_datalogger = Equipment(
                            type="DATALOGGER",
                            manufacturer=datalogger.manufacturer,
                            model=datalogger.model,
                            description=dl_desc,
                            serial_number=str(cha.datalogger_serial_number) if cha.datalogger_serial_number else None
                        )

                    # 4. CHANNEL ASSEMBLY
                    cha_types = [t.strip() for t in getattr(cha, 'types', 'CONTINUOUS,GEOPHYSICAL').split(',')] if getattr(cha, 'types', None) else None
                    
                    cha_clock_drift = getattr(cha, 'clock_drift', 0.0)
                    if (not cha_clock_drift or cha_clock_drift == 0.0) and datalogger:
                        cha_clock_drift = getattr(datalogger, 'max_clock_drift', 0.0)

                    obspy_cha = Channel(
                        code=cha.code,
                        location_code=cha.location_code,
                        latitude=lat,
                        longitude=lon,
                        elevation=elev,
                        depth=cha.depth,
                        sample_rate=cha.sample_rate,
                        clock_drift_in_seconds_per_sample=cha_clock_drift,
                        calibration_units=getattr(cha, 'calibration_units', None),
                        azimuth=cha.azimuth,
                        dip=cha.dip,
                        types=cha_types,
                        start_date=self._parse_date(cha.start_date),
                        end_date=self._parse_date(cha.end_date),
                        restricted_status=getattr(cha, 'restricted_status', None) or 'open', # <--- ADDED HERE!
                        sensor=obspy_equip_sensor,
                        data_logger=obspy_equip_datalogger,
                        pre_amplifier=obspy_equip_preamp,
                        response=obspy_response
                    )
                    obspy_cha.comments = self._build_fdsn_comments(getattr(cha, 'comments', None))
                                        
                    obspy_sta.channels.append(obspy_cha)
                
                obspy_net.stations.append(obspy_sta)
            inv.networks.append(obspy_net)

        if cancel_callback and cancel_callback():
            return None
        cur += 1
        if output_path:
            self._emit_export_progress(
                progress_callback, cur, total, f"Writing StationXML to disk…"
            )
            inv.write(output_path, format="STATIONXML", validate=validate)
        else:
            self._emit_export_progress(
                progress_callback, cur, total, "Inventory build complete."
            )
        return inv

    def inventory_to_stationxml_bytes(
        self,
        inv: Inventory,
        progress_callback: ProgressCallback = None,
    ) -> bytes:
        """Serialize a single ObsPy inventory to StationXML bytes."""
        self._emit_export_progress(
            progress_callback, 0, 2, "Serializing inventory to StationXML bytes…"
        )
        buf = io.BytesIO()
        inv.write(buf, format="STATIONXML")
        self._emit_export_progress(progress_callback, 2, 2, "Serialization complete.")
        return buf.getvalue()

    def _first_station_code_in_inventory(self, inv: Inventory) -> Optional[str]:
        for net in inv.networks or []:
            for sta in net.stations or []:
                return sta.code
        return None

    def _safe_xml_filename(self, station_code: str, used: Set[str]) -> str:
        """FDSN-safe filename {code}.xml, disambiguated if the same code appears twice in the ZIP."""
        base = (station_code or "station").strip() or "station"
        safe = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in base.upper())[:32]
        name = f"{safe}.xml"
        if name not in used:
            used.add(name)
            return name
        i = 1
        while True:
            cand = f"{safe}_{i}.xml"
            if cand not in used:
                used.add(cand)
                return cand
            i += 1

    def _station_export_code(self, station_id: int) -> str:
        """Return station code when possible for per-station filenames."""
        for net in self.net_ctrl.get_all_networks():
            for sta in self.sta_ctrl.get_stations_by_network(net.id):
                if sta.id == station_id:
                    return str(sta.code or "").upper()
        return f"id{station_id}"

    def station_xml_filename(self, station_id: int, used: Optional[Set[str]] = None) -> str:
        """Filename for one station export: STATION.xml, sanitized and optionally unique."""
        used_names = used if used is not None else set()
        return self._safe_xml_filename(self._station_export_code(station_id), used_names)

    def build_station_inventory(
        self,
        station_id: int,
        *,
        output_path: Optional[str] = None,
        validate: bool = True,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ) -> Optional[Inventory]:
        """Build an ObsPy Inventory containing exactly one station and its parent network."""
        return self.build_inventory(
            target_station_id=station_id,
            output_path=output_path,
            validate=validate,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )

    def build_stationxml_bytes(
        self,
        station_id: int,
        *,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ) -> Optional[bytes]:
        """Build and serialize one station StationXML document."""
        inv = self.build_station_inventory(
            station_id,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )
        if inv is None:
            return None
        return self.inventory_to_stationxml_bytes(inv)

    def build_zip_bytes_for_station_ids(
        self,
        station_ids: List[int],
        *,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ) -> Optional[bytes]:
        """
        One StationXML file per station ID inside a ZIP archive.
        Filenames default to {station_code}.xml (disambiguated on collision).
        """
        if not station_ids:
            raise ValueError("station_ids must not be empty")
        n = len(station_ids)
        total = n + 2
        cur = 0
        self._emit_export_progress(progress_callback, cur, total, "Preparing ZIP export…")
        if cancel_callback and cancel_callback():
            return None
        cur = 1
        self._emit_export_progress(progress_callback, cur, total, "Building ZIP archive…")
        if cancel_callback and cancel_callback():
            return None

        used_names: Set[str] = set()
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, sid in enumerate(station_ids):
                if cancel_callback and cancel_callback():
                    return None
                cur += 1
                self._emit_export_progress(
                    progress_callback,
                    cur,
                    total,
                    f"Station {idx + 1}/{n} (id={sid}) — building XML…",
                )
                inv = self.build_station_inventory(
                    sid,
                    progress_callback=None,
                    cancel_callback=cancel_callback,
                )
                if inv is None:
                    return None
                fname = self.station_xml_filename(sid, used_names)
                zf.writestr(fname, self.inventory_to_stationxml_bytes(inv))

        if cancel_callback and cancel_callback():
            return None
        cur += 1
        self._emit_export_progress(progress_callback, cur, total, "Finalizing ZIP…")
        return zip_buf.getvalue()