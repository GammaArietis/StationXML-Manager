import logging
import json
from typing import Callable, Optional

from obspy import read_inventory
from obspy.core.inventory.response import (PolesZerosResponseStage, FIRResponseStage,
                                           CoefficientsTypeResponseStage, ResponseStage)

from core.models.base_models import (Network, Station, Operator, Sensor, Datalogger,
                                    PoleZero, Channel, ResponseFilter, Preamplifier, AnalogStage,
                                    coerce_fdsn_restricted_status)
                                    
from utils.fdsn_coordinates import resolve_channel_position
from utils.nrl_client import NRLManager

logger = logging.getLogger(__name__)

# (current, total, message) — total==0 means indeterminate phase (e.g. reading file).
ProgressCallback = Optional[Callable[[int, int, str], None]]
CancelCallback = Optional[Callable[[], bool]]


class StationXMLImportError(RuntimeError):
    """Raised when StationXML parsing or persistence fails with actionable detail."""


class StationXMLParser:
    def __init__(self, net_ctrl, sta_ctrl, cha_ctrl, equ_ctrl):
        self.net_ctrl = net_ctrl
        self.sta_ctrl = sta_ctrl
        self.cha_ctrl = cha_ctrl
        self.eq_ctrl = equ_ctrl
    
    def _extract_comments(self, obspy_obj):
        """Extracts complex FDSN comments and saves them as a structured JSON list."""
        if not hasattr(obspy_obj, 'comments') or not obspy_obj.comments:
            return None
        
        comments_list = []
        for c in obspy_obj.comments:
            if not c.value:
                continue
                
            # Build the data structure for each individual comment
            comment_dict = {
                "value": str(c.value),
                "subject": str(getattr(c, 'subject', "")) or "",
                "begin_date": self._format_date(getattr(c, 'begin_date', None)),
                "end_date": self._format_date(getattr(c, 'end_date', None)),
                "author_name": "",
                "author_agency": ""
            }
            
            # If there is an author (Person object in ObsPy), extract name and agency
            if hasattr(c, 'authors') and c.authors:
                author = c.authors[0]
                if hasattr(author, 'names') and author.names:
                    comment_dict["author_name"] = str(author.names[0])
                if hasattr(author, 'agency') and author.agency:
                    comment_dict["author_agency"] = str(author.agency)
                    
            comments_list.append(comment_dict)
            
        # Return the JSON (e.g. [{"value": "Maintenance", "begin_date": "..."}])
        return json.dumps(comments_list) if comments_list else None

    @staticmethod
    def _emit_progress(
        progress_callback: ProgressCallback,
        current: int,
        total: int,
        message: str,
    ) -> None:
        if not progress_callback:
            return
        try:
            progress_callback(current, total, message)
        except Exception as exc:
            logger.warning("progress_callback failed: %s", exc)

    @staticmethod
    def _import_total_steps(inv) -> int:
        """1 = read file step; then each network, station, and channel in the ObsPy tree."""
        total = 1
        for net in inv:
            total += 1
            for sta in net:
                total += 1
                total += len(list(sta))
        return total

    def import_file(
        self,
        file_path,
        progress_callback: ProgressCallback = None,
        cancel_callback: CancelCallback = None,
    ):
        """
        Import a StationXML (or inventory) file into the database.

        progress_callback(current, total, message):
            total==0 only for the initial "reading file" phase; afterwards total matches
            the planned step count until completion (current == total).
        cancel_callback():
            if provided and returns True, import stops and the method returns False.
        """
        try:
            self._emit_progress(
                progress_callback, 0, 0, "Reading StationXML file…"
            )
            if cancel_callback and cancel_callback():
                return False

            inv = read_inventory(file_path)
            logger.info("File %s loaded with ObsPy. Starting parsing...", file_path)

            total = self._import_total_steps(inv)
            current = 1
            self._emit_progress(
                progress_callback,
                current,
                total,
                f"Inventory loaded ({len(inv)} network(s)); importing…",
            )

            for net in inv:
                if cancel_callback and cancel_callback():
                    return False
                net_op_id = self._get_or_create_operator(net)
                db_net = self._process_network(net, net_op_id)
                current += 1
                self._emit_progress(
                    progress_callback,
                    current,
                    total,
                    f"Network {getattr(net, 'code', '?')}: saved metadata",
                )
                if not db_net:
                    for sta in net:
                        if cancel_callback and cancel_callback():
                            return False
                        current += 1
                        self._emit_progress(
                            progress_callback,
                            current,
                            total,
                            f"Station {getattr(sta, 'code', '?')}: skipped (network not stored)",
                        )
                        for cha in sta:
                            if cancel_callback and cancel_callback():
                                return False
                            current += 1
                            self._emit_progress(
                                progress_callback,
                                current,
                                total,
                                f"Channel {getattr(cha, 'code', '?')}: skipped",
                            )
                    continue

                for sta in net:
                    if cancel_callback and cancel_callback():
                        return False
                    sta_op_id = self._get_or_create_operator(sta)
                    db_sta = self._process_station(sta, db_net.id, sta_op_id)
                    current += 1
                    self._emit_progress(
                        progress_callback,
                        current,
                        total,
                        f"Station {getattr(sta, 'code', '?')}: saved metadata",
                    )
                    if not db_sta:
                        for cha in sta:
                            if cancel_callback and cancel_callback():
                                return False
                            current += 1
                            self._emit_progress(
                                progress_callback,
                                current,
                                total,
                                f"Channel {getattr(cha, 'code', '?')}: skipped (station not stored)",
                            )
                        continue

                    for cha in sta:
                        if cancel_callback and cancel_callback():
                            return False
                        self._process_channel(cha, db_sta.id, sta)
                        current += 1
                        loc = getattr(cha, "location_code", "") or "--"
                        self._emit_progress(
                            progress_callback,
                            current,
                            total,
                            f"Channel {getattr(sta, 'code', '?')}.{getattr(cha, 'code', '?')} ({loc})",
                        )

            self._emit_progress(
                progress_callback, total, total, "Import completed successfully."
            )
            return True
        except StationXMLImportError:
            raise
        except Exception as e:
            logger.exception("Errore critico durante l'importazione StationXML")
            raise StationXMLImportError(
                f"Importazione StationXML fallita: {e}"
            ) from e

    def _get_or_create_operator(self, obspy_obj):
        """Extracts the operator from a Network or Station and saves it if new."""
        if not hasattr(obspy_obj, 'operators') or not obspy_obj.operators:
            return None
        
        op_data = obspy_obj.operators[0]
        agency = op_data.agency if hasattr(op_data, 'agency') and op_data.agency else "Unknown"
        
        # FIX: Retrieve Website
        website = getattr(op_data, 'website', None)
        if website: website = str(website).strip()
        
        contact_name = None
        contact_email = None
        phone_cc, phone_ac, phone_num = 39, 0, None
        
        if hasattr(op_data, 'contacts') and op_data.contacts:
            person = op_data.contacts[0]
            if hasattr(person, 'names') and person.names:
                contact_name = person.names[0]
            if hasattr(person, 'emails') and person.emails:
                contact_email = person.emails[0]
            if hasattr(person, 'phones') and person.phones:
                ph = person.phones[0]
                phone_cc = getattr(ph, 'country_code', 39)
                phone_ac = getattr(ph, 'area_code', 0)
                phone_num = getattr(ph, 'phone_number', str(ph))
                
        existing_op = self.eq_ctrl.get_operator_by_details(agency, contact_name, contact_email)
        if existing_op:
            # FIX: Access the ID safely for both objects and DB rows
            return existing_op.id if hasattr(existing_op, 'id') else existing_op['id']

        by_agency = self.eq_ctrl.get_operator_by_agency(agency)
        if by_agency:
            return by_agency.id if hasattr(by_agency, 'id') else by_agency['id']
        
        new_op = Operator(
            agency=agency,
            contact_name=contact_name,
            contact_email=contact_email,
            website=website,  # <--- FIX
            phone_country_code=phone_cc,
            phone_area_code=phone_ac,
            phone_number=phone_num
        )
        
        saved_op = self.eq_ctrl.save_operator(new_op)
        return saved_op.id if saved_op else None

    def _format_date(self, obspy_date):
        if obspy_date is None: return None
        return obspy_date.strftime("%Y-%m-%dT%H:%M:%S")

    def _process_network(self, obspy_net, operator_id):
        start_date_str = self._format_date(obspy_net.start_date)
        end_date_str = self._format_date(obspy_net.end_date)
        
        # --- NEW: Extraction of structured comments in JSON ---
        comments_json = self._extract_comments(obspy_net)
        
        # Check if it already exists
        existing_nets = self.net_ctrl.get_all_networks()
        for net in existing_nets:
            if net.code == obspy_net.code and net.start_date == start_date_str:
                return net

        doi_str = obspy_net.identifiers[0] if hasattr(obspy_net, 'identifiers') and obspy_net.identifiers else None
            
        net_model = Network(
            code=obspy_net.code,
            description=obspy_net.description,
            start_date=start_date_str,
            end_date=end_date_str,
            doi=doi_str,
            operator_id=operator_id,
            restricted_status=coerce_fdsn_restricted_status(
                getattr(obspy_net, "restricted_status", None)
            ),
            comments=comments_json  # <--- Save JSON
        )
        return self.net_ctrl.save_network(net_model)

    def _process_station(self, obspy_sta, net_id, operator_id):
        start_date_str = self._format_date(obspy_sta.start_date)
        end_date_str = self._format_date(obspy_sta.end_date)
        creation_date_str = self._format_date(getattr(obspy_sta, 'creation_date', None))
        
        comments = self._extract_comments(obspy_sta)
        
        existing_stas = self.sta_ctrl.get_stations_by_network(net_id)
        for sta in existing_stas:
            if sta.code == obspy_sta.code and sta.start_date == start_date_str:
                return sta

        s_desc = s_town = s_county = s_region = s_country = None
        if hasattr(obspy_sta, 'site') and obspy_sta.site:
            s_desc = getattr(obspy_sta.site, 'description', None)
            s_town = getattr(obspy_sta.site, 'town', None)
            s_county = getattr(obspy_sta.site, 'county', None)
            s_region = getattr(obspy_sta.site, 'region', None)
            s_country = getattr(obspy_sta.site, 'country', None)

        sta_model = Station(
            network_id=net_id, code=obspy_sta.code, latitude=obspy_sta.latitude,
            longitude=obspy_sta.longitude, elevation=obspy_sta.elevation,
            site_name=obspy_sta.site.name if hasattr(obspy_sta, 'site') and obspy_sta.site else "",
            start_date=start_date_str, end_date=end_date_str, creation_date=creation_date_str,
            operator_id=operator_id, vault=getattr(obspy_sta, 'vault', None),
            geology=getattr(obspy_sta, 'geology', None),
            restricted_status=coerce_fdsn_restricted_status(
                getattr(obspy_sta, "restricted_status", None)
            ),
            water_level=getattr(obspy_sta, 'water_level', None),
            description=s_desc, town=s_town, county=s_county,
            region=s_region, country=s_country, comments=comments
            )
        return self.sta_ctrl.save_station(sta_model)

    def _process_channel(self, obspy_cha, sta_id, obspy_sta):
        logger.info(f"  -> Parsing Channel: {obspy_cha.code}")
        start_date_str = self._format_date(obspy_cha.start_date)
        
        comments = self._extract_comments(obspy_cha)
        
        # Duplicate check
        for cha in self.cha_ctrl.get_channels_by_station(sta_id):
            if cha.code == obspy_cha.code and cha.location_code == obspy_cha.location_code and cha.start_date == start_date_str:
                return

        # 1. Parsing Instruments and Response (Now retrieves 4 parameters, including pa_id!)
        sensor_id, datalogger_id, pa_id, pa_gain = self._parse_equipment_from_response(obspy_cha)
        
        # 2. Retrieve Overall Sensitivity
        overall_sens = None
        if hasattr(obspy_cha, 'response') and obspy_cha.response:
            if hasattr(obspy_cha.response, 'instrument_sensitivity') and obspy_cha.response.instrument_sensitivity:
                overall_sens = obspy_cha.response.instrument_sensitivity.value

        # 3. FIX CALIBRATION UNITS (Correctly reads 'm/s' from XML)
        cal_units = None
        cal_obj = getattr(obspy_cha, 'calibration_units', None)
        if cal_obj:
            cal_units = getattr(cal_obj, 'name', str(cal_obj))

        # 4. Safe Serial Extraction (Prevents writing "None" to DB)
        s_serial = ""
        if hasattr(obspy_cha, 'sensor') and obspy_cha.sensor and getattr(obspy_cha.sensor, 'serial_number', None):
            s_serial = str(obspy_cha.sensor.serial_number)
            
        dl_serial = ""
        if hasattr(obspy_cha, 'data_logger') and obspy_cha.data_logger and getattr(obspy_cha.data_logger, 'serial_number', None):
            dl_serial = str(obspy_cha.data_logger.serial_number)
            
        pa_serial = ""
        if hasattr(obspy_cha, 'pre_amplifier') and obspy_cha.pre_amplifier and getattr(obspy_cha.pre_amplifier, 'serial_number', None):
            pa_serial = str(obspy_cha.pre_amplifier.serial_number)

        c_drift = getattr(obspy_cha, 'clock_drift_in_seconds_per_sample', 0.0)

        ch_lat, ch_lon, ch_elev = resolve_channel_position(
            getattr(obspy_cha, 'latitude', None),
            getattr(obspy_cha, 'longitude', None),
            getattr(obspy_cha, 'elevation', None),
            obspy_sta.latitude,
            obspy_sta.longitude,
            obspy_sta.elevation,
        )

        # 5. Model Creation and Saving
        cha_model = Channel(
            station_id=sta_id,
            code=obspy_cha.code,
            location_code=obspy_cha.location_code,
            latitude=ch_lat,
            longitude=ch_lon,
            elevation=ch_elev,
            depth=getattr(obspy_cha, 'depth', 0.0),
            azimuth=getattr(obspy_cha, 'azimuth', 0.0),
            dip=getattr(obspy_cha, 'dip', 0.0),
            sample_rate=getattr(obspy_cha, 'sample_rate', 0.0),
            start_date=start_date_str,
            end_date=self._format_date(obspy_cha.end_date),
            sensor_id=sensor_id,
            datalogger_id=datalogger_id,
            pre_amplifier_id=pa_id,  # <-- FIX: Now passing the correct ID from catalog!
            pre_amplifier_serial_number=pa_serial,
            pre_amplifier_gain=pa_gain,
            overall_sensitivity=overall_sens,
            sensor_serial_number=s_serial,
            datalogger_serial_number=dl_serial,
            types=",".join(obspy_cha.types) if getattr(obspy_cha, 'types', None) else "CONTINUOUS,GEOPHYSICAL",
            restricted_status=coerce_fdsn_restricted_status(
                getattr(obspy_cha, "restricted_status", None)
            ),
            clock_drift=c_drift,
            calibration_units=cal_units,
            comments=comments
        )
        
        self.cha_ctrl.save_channel(cha_model)

    def _parse_equipment_from_response(self, obspy_cha):
        """FDSN Hybrid Parser: Priority split on space, fallback on underscore."""
        
        nrl_mgr = NRLManager()
        
        def smart_split(source_str, default_mfg, default_model):
            if not source_str or len(source_str) < 3:
                return default_mfg, default_model
            
            source_str = source_str.strip().upper()
            
            # 3. Cut by Space (e.g. NANOMETRICS TRILLIUM)
            if " " in source_str:
                parts = source_str.split(" ", 1)
                return parts[0].strip(), parts[1].strip()
            
            # 1. Cut by Underscore (e.g. GURALP_CMG3T)
            if "_" in source_str:
                parts = source_str.split("_", 1)
                return parts[0].strip(), parts[1].strip()
                
            # 2. Cut by Dash (e.g. GURALP-CMG3T)
            if "-" in source_str:
                parts = source_str.split("-", 1)
                return parts[0].strip(), parts[1].strip()
                
            # 4. Fallback (e.g. just "TRILLIUM")
            return default_mfg, source_str

        # --- 1. METADATA ANALYSIS (Sensor and Datalogger) ---
        s_obj = getattr(obspy_cha, 'sensor', None)
        sensor_type = str(getattr(s_obj, 'type', "SENSOR") or "SENSOR")
        sensor_mfg = str(getattr(s_obj, 'manufacturer', "") or "UNKNOWN").strip().upper()
        sensor_model = str(getattr(s_obj, 'model', "") or "UNKNOWN").strip().upper()
        desc_s = str(getattr(s_obj, 'description', "") or "").strip()
        
        if (sensor_mfg == "UNKNOWN" or sensor_model == "UNKNOWN") and desc_s.startswith("NRL:"):
            parts = desc_s.replace("NRL:", "").split("->")
            if len(parts) >= 2:
                if sensor_mfg == "UNKNOWN": sensor_mfg = parts[0].strip().upper()
                if sensor_model == "UNKNOWN": sensor_model = " ".join(parts[1:]).strip().upper()
        elif sensor_mfg == "UNKNOWN":
            source = desc_s if (len(desc_s) > 5) else sensor_model
            sensor_mfg, sensor_model = smart_split(source, sensor_mfg, sensor_model)

        dl_obj = getattr(obspy_cha, 'data_logger', None)
        dl_mfg = str(getattr(dl_obj, 'manufacturer', "") or "UNKNOWN").strip().upper()
        dl_model = str(getattr(dl_obj, 'model', "") or "UNKNOWN").strip().upper()
        desc_dl = str(getattr(dl_obj, 'description', "") or "").strip()
        
        if (dl_mfg == "UNKNOWN" or dl_model == "UNKNOWN") and desc_dl.startswith("NRL:"):
            parts = desc_dl.replace("NRL:", "").split("->")
            if len(parts) >= 2:
                if dl_mfg == "UNKNOWN": dl_mfg = parts[0].strip().upper()
                if dl_model == "UNKNOWN": dl_model = " ".join(parts[1:]).strip().upper()
        elif dl_mfg == "UNKNOWN":
            source = desc_dl if (len(desc_dl) > 3) else dl_model
            dl_mfg, dl_model = smart_split(source, dl_mfg, dl_model)
            
        pa_obj = getattr(obspy_cha, 'pre_amplifier', None)
        pa_mfg = str(getattr(pa_obj, 'manufacturer', "") or "GENERIC").strip().upper()
        pa_model_base = str(getattr(pa_obj, 'model', "") or "PREAMP").strip().upper()

        # --- 2. TECHNICAL PARAMETERS AND STAGES ---
        s_sens, s_freq, s_norm_f, s_norm_q = None, None, 1.0, 1.0
        paz_zeros, paz_poles = [], []
        pz_unit_type = "LAPLACE (RADIANS/SECOND)"
        s_in_units = "m/s"   # Variables to dynamically capture units
        s_out_units = "V"
        
        d_gain, base_hw_delay, base_hw_corr = 0.0, 0.0, 0.0
        response_filters = []
        analog_stages_list = []
        pa_model_parts = []
        
        valid_v_units = ["V", "VOLT", "VOLTS", "MV", "MILLIVOLT", "MILLIVOLTS"]

        if hasattr(obspy_cha, 'response') and obspy_cha.response and obspy_cha.response.response_stages:
            for stage in obspy_cha.response.response_stages:
                c_delay = getattr(stage, 'decimation_delay', 0.0) or 0.0
                c_corr = getattr(stage, 'decimation_correction', 0.0) or 0.0
                in_u = str(stage.input_units or "").strip().upper()
                out_u = str(stage.output_units or "").strip().upper()

                # 1. SENSOR STAGE (Physical -> Volt)
                if out_u in valid_v_units and in_u not in valid_v_units and in_u not in ["COUNT", "COUNTS"]:
                    s_sens = getattr(stage, 'stage_gain', 1.0)
                    s_freq = getattr(stage, 'stage_gain_frequency', 1.0)
                    s_norm_f = getattr(stage, 'normalization_factor', 1.0)
                    s_norm_q = getattr(stage, 'normalization_frequency', 1.0)
                    pz_unit_type = getattr(stage, 'pz_transfer_function_type', pz_unit_type)
                    
                    # CRITICAL FIX: Capture REAL units (e.g. m/s**2)
                    s_in_units = str(stage.input_units or "m/s").strip()
                    s_out_units = str(stage.output_units or "V").strip()
                    
                    paz_zeros = [PoleZero(z.real, z.imag) for z in stage.zeros] if hasattr(stage, 'zeros') and stage.zeros else []
                    paz_poles = [PoleZero(p.real, p.imag) for p in stage.poles] if hasattr(stage, 'poles') and stage.poles else []
                    
                # 2. INTERMEDIATE ANALOG STAGES (Volt -> Volt)
                elif in_u in valid_v_units and out_u in valid_v_units:
                    st_gain = getattr(stage, 'stage_gain', 1.0) or 1.0
                    st_name = str(getattr(stage, 'name', "") or getattr(stage, 'description', "")).strip().upper()
                    
                    if st_name and st_name not in pa_model_parts and st_name not in ["PREAMP", "FILTER", "ANALOG FILTER"]:
                        pa_model_parts.append(st_name)
                        
                    st_zeros = [PoleZero(z.real, z.imag) for z in stage.zeros] if hasattr(stage, 'zeros') and stage.zeros else []
                    st_poles = [PoleZero(p.real, p.imag) for p in stage.poles] if hasattr(stage, 'poles') and stage.poles else []
                    
                    new_analog_stage = AnalogStage(
                        stage_sequence=stage.stage_sequence_number, stage_gain=st_gain,
                        input_units=in_u, output_units=out_u, name=st_name, poles=st_poles, zeros=st_zeros
                    )
                    analog_stages_list.append(new_analog_stage)
                    
                # 3 and 4. CATCH-ALL: Datalogger A/D, FIR and Pure Decimators
                else:
                    in_u = str(getattr(stage, 'input_units', '') or '').strip().upper()
                    out_u = str(getattr(stage, 'output_units', '') or '').strip().upper()
                    
                    if not in_u: in_u = "COUNTS"
                    if not out_u: out_u = "COUNTS"

                    sg = getattr(stage, 'stage_gain', 1.0) or 1.0
                    
                    if out_u in ["COUNT", "COUNTS", "DIGITAL COUNTS"] and in_u not in ["COUNT", "COUNTS", "DIGITAL COUNTS"]:
                        f_type = "A/D"
                        if sg > 0.0: d_gain = sg
                    else:
                        coeffs = getattr(stage, 'coefficients', None) or getattr(stage, 'numerator', None)
                        if coeffs is not None and len(list(coeffs)) > 0: f_type = "FIR"
                        else: f_type = "DECIMATION"
                            
                    payload_coeffs = list(coeffs) if f_type == "FIR" and coeffs is not None else []
                    payload = {
                        "type": f_type, "coefficients": payload_coeffs, "input_units": in_u, "output_units": out_u,
                        "stage_gain": sg, "stage_gain_frequency": getattr(stage, 'stage_gain_frequency', 0.0) or 0.0
                    }
                    
                    response_filters.append(ResponseFilter(
                        stage_number=stage.stage_sequence_number, filter_type=f_type,
                        coefficients=json.dumps(payload), decimation_factor=getattr(stage, 'decimation_factor', 1) or 1,
                        input_sample_rate=getattr(stage, 'decimation_input_sample_rate', 0.0) or 0.0,
                        output_sample_rate=getattr(stage, 'decimation_output_sample_rate', 0.0) or 0.0,
                        estimated_delay=c_delay, correction_applied=c_corr
                    ))
                            
        # --- 3. SAVING TO CATALOG ---
        existing_s = self.eq_ctrl.get_all_sensors()
        match_s = None
        s_base, s_count = sensor_model, 1
        
        # Helper function to compare two PoleZero lists with tolerance
        def check_pz_match(list1, list2, tol=1e-5):
            if len(list1) != len(list2): return False
            if len(list1) == 0: return True
            # Sort by real then imaginary part for stable comparisons
            l1_sorted = sorted(list1, key=lambda pz: (getattr(pz, 'real', 0), getattr(pz, 'imag', 0)))
            l2_sorted = sorted(list2, key=lambda pz: (getattr(pz, 'real', 0), getattr(pz, 'imag', 0)))
            for pz1, pz2 in zip(l1_sorted, l2_sorted):
                r1 = getattr(pz1, 'real', 0); i1 = getattr(pz1, 'imag', 0)
                r2 = getattr(pz2, 'real', 0); i2 = getattr(pz2, 'imag', 0)
                if abs(r1 - r2) > tol or abs(i1 - i2) > tol:
                    return False
            return True

        for s in existing_s:
            m_mod = s.model if hasattr(s, 'model') else s['model']
            m_mfg = s.manufacturer if hasattr(s, 'manufacturer') else s['manufacturer']
            
            # Base Match: Same Manufacturer and Model root (e.g. LE3D-5S)
            if m_mod.startswith(s_base) and m_mfg == sensor_mfg:
                
                m_sens = s.sensitivity if hasattr(s, 'sensitivity') else s['sensitivity']
                m_freq = s.frequency if hasattr(s, 'frequency') else s['frequency']
                
                # Retrieve Poles and Zeros from DB (might be in dict or obj)
                m_zeros = getattr(s, 'zeros', []) if hasattr(s, 'zeros') else s.get('zeros', [])
                m_poles = getattr(s, 'poles', []) if hasattr(s, 'poles') else s.get('poles', [])
                
                # Mathematical Match: Sensitivity, Frequency AND Pole/Zero tables
                sens_match = (m_sens == s_sens or s_sens is None)
                freq_match = (m_freq == s_freq or s_freq is None)
                zeros_match = check_pz_match(m_zeros, paz_zeros)
                poles_match = check_pz_match(m_poles, paz_poles)
                
                # Final Verdict
                if sens_match and freq_match and zeros_match and poles_match:
                    match_s = s
                    sensor_model = m_mod # Use exact saved name
                    break
                else:
                    s_count += 1 # Increment to create Variant
                    
        # If no match, name the variant
        if not match_s and s_count > 1:
            sensor_model = f"{s_base} V{s_count}"
            
        if match_s:
            s_id = match_s.id if hasattr(match_s, 'id') else match_s['id']
        else:
            nrl_path_recuperato = nrl_mgr.try_reconstruct_nrl_path(desc_s, "SENSOR")
            # 1. Creation of raw object with fallback
            new_sensor = Sensor(
                manufacturer=sensor_mfg, model=sensor_model,
                type="SENSOR", # Temporary fallback
                description=desc_s,
                nrl_path=nrl_path_recuperato,
                sensitivity=s_sens, frequency=s_freq,
                normalization_factor=s_norm_f, normalization_freq=s_norm_q,
                input_units=s_in_units, output_units=s_out_units,
                pz_transfer_function_type=pz_unit_type,
                zeros=paz_zeros, poles=paz_poles
            )
            
            # 2. Physical Auto-classification (Delegated to Controller!)
            new_sensor.type = self.eq_ctrl.auto_classify_sensor_type(new_sensor)
            
            # 3. Saving
            saved_s = self.eq_ctrl.save_sensor(new_sensor)
            if isinstance(saved_s, int) and not isinstance(saved_s, bool): s_id = saved_s
            elif hasattr(saved_s, 'id'): s_id = saved_s.id
            else:
                try:
                    with self.eq_ctrl.dao.db.get_connection() as conn:
                        res = conn.execute(
                            "SELECT id FROM sensor_catalog WHERE model=?",
                            (sensor_model,),
                        ).fetchone()
                        s_id = res['id'] if res else None
                except Exception as exc:
                    logger.warning(
                        "Fallback lookup sensore fallito per modello %r "
                        "(manufacturer=%r, channel=%r): %s",
                        sensor_model,
                        sensor_mfg,
                        getattr(obspy_cha, "code", "?"),
                        exc,
                    )
                    s_id = None

        # ==========================================
        # DATALOGGER MATCHING (Mathematical Engine)
        # ==========================================
        existing_d = self.eq_ctrl.get_all_dataloggers()
        match_d = None
        d_base = dl_model
        d_count = 1
        
        # Calculate final Sample Rate to give a "descriptive" name to variants (e.g. 100Hz)
        out_rate_str = "MIX"
        if response_filters:
            sorted_resp_f = sorted(response_filters, key=lambda x: getattr(x, 'stage_number', 0))
            last_out = getattr(sorted_resp_f[-1], 'output_sample_rate', 0.0)
            if last_out and last_out > 0:
                out_rate_str = f"{last_out:g}Hz"

        for d in existing_d:
            m_mod = d.model if hasattr(d, 'model') else d['model']
            m_mfg = d.manufacturer if hasattr(d, 'manufacturer') else d['manufacturer']
            m_gain = d.gain if hasattr(d, 'gain') else d['gain']
            db_filters = d.filters if hasattr(d, 'filters') else (d.get('filters', []) if isinstance(d, dict) else [])
            
            # 1. Base Match: Same Manufacturer and Model "Family"
            if m_mod.startswith(d_base) and m_mfg == dl_mfg:
                
                # 2. Mathematical Match: Compare filter chains
                filters_match = True
                if len(db_filters) != len(response_filters):
                    filters_match = False # Missing or extra stage!
                else:
                    db_f_sorted = sorted(db_filters, key=lambda x: getattr(x, 'stage_number', 0))
                    new_f_sorted = sorted(response_filters, key=lambda x: getattr(x, 'stage_number', 0))
                    
                    for f_db, f_new in zip(db_f_sorted, new_f_sorted):
                        # If filter type or decimation factor changes, math is different
                        if getattr(f_db, 'filter_type', '') != getattr(f_new, 'filter_type', ''):
                            filters_match = False; break
                        if getattr(f_db, 'decimation_factor', 1) != getattr(f_new, 'decimation_factor', 1):
                            filters_match = False; break
                            
                        # Safe extraction of Delay and Correction (handles DB objects or dicts)
                        db_delay = getattr(f_db, 'estimated_delay', 0.0) if hasattr(f_db, 'estimated_delay') else (f_db.get('estimated_delay', 0.0) if isinstance(f_db, dict) else 0.0)
                        db_corr = getattr(f_db, 'correction_applied', 0.0) if hasattr(f_db, 'correction_applied') else (f_db.get('correction_applied', 0.0) if isinstance(f_db, dict) else 0.0)
                        
                        new_delay = getattr(f_new, 'estimated_delay', 0.0) or 0.0
                        new_corr = getattr(f_new, 'correction_applied', 0.0) or 0.0
                        
                        # Delay and Correction check with tolerance (1 microsecond)
                        if abs(db_delay - new_delay) > 1e-6:
                            filters_match = False; break
                        if abs(db_corr - new_corr) > 1e-6:
                            filters_match = False; break
                            
                # 3. Verdict: If filters AND gain are identical, it's a Perfect Match
                if filters_match and (m_gain == d_gain or not m_gain or m_gain == 0.0):
                    match_d = d
                    dl_model = m_mod # Keep exact name already saved in DB
                    break
                else:
                    d_count += 1
                    
        # 4. Saving or Retrieving ID
        if match_d:
            d_id = match_d.id if hasattr(match_d, 'id') else match_d['id']
        else:
            if d_count > 1:
                # Descriptive Variant: e.g. "CENTAUR [100Hz v2]"
                dl_model = f"{d_base} [{out_rate_str} v{d_count}]"
            
            nrl_path_recuperato_dl = nrl_mgr.try_reconstruct_nrl_path(desc_dl, "DATALOGGER")
            
            new_dl = Datalogger(
                manufacturer=dl_mfg, model=dl_model,
                description=desc_dl,
                nrl_path=nrl_path_recuperato_dl,
                gain=d_gain,
                max_clock_drift=getattr(obspy_cha, 'clock_drift_in_seconds_per_sample', 0.0),
                base_hardware_delay=base_hw_delay, base_hardware_correction=base_hw_corr,
                filters=response_filters
            )
            saved_d = self.eq_ctrl.save_datalogger(new_dl)
            if isinstance(saved_d, int) and not isinstance(saved_d, bool):
                d_id = saved_d
            elif hasattr(saved_d, 'id'):
                d_id = saved_d.id
            else:
                try:
                    with self.eq_ctrl.dao.db.get_connection() as conn:
                        res = conn.execute(
                            "SELECT id FROM datalogger_catalog WHERE model=?",
                            (dl_model,),
                        ).fetchone()
                        d_id = res['id'] if res else None
                except Exception as exc:
                    logger.warning(
                        "Fallback lookup datalogger fallito per modello %r "
                        "(manufacturer=%r, channel=%r): %s",
                        dl_model,
                        dl_mfg,
                        getattr(obspy_cha, "code", "?"),
                        exc,
                    )
                    d_id = None
        
        pa_id = None
        pa_gain_total = 1.0
        
        for ast in analog_stages_list:
            pa_gain_total *= ast.stage_gain
            
        if analog_stages_list:
            if pa_model_parts:
                pa_model = " + ".join(pa_model_parts)
                if len(pa_model) > 50:
                    pa_model = "MULTI-STAGE ANALOG CONDITIONING"
            else:
                pa_model = pa_model_base if pa_model_base != "PREAMP" else "ANALOG CONDITIONING STAGES"
                
            existing_pa = self.eq_ctrl.get_all_preamplifiers()
            for pa in existing_pa:
                m_mod = pa.model if hasattr(pa, 'model') else pa['model']
                m_mfg = pa.manufacturer if hasattr(pa, 'manufacturer') else pa['manufacturer']
                if m_mod == pa_model and m_mfg == pa_mfg:
                    pa_id = pa.id if hasattr(pa, 'id') else pa['id']
                    break
            
            if not pa_id:
                new_pa = Preamplifier(
                    manufacturer=pa_mfg, model=pa_model,
                    description=f"Analog conditioning ({len(analog_stages_list)} stages)",
                    analog_stages=analog_stages_list
                )
                saved_pa = self.eq_ctrl.save_preamplifier(new_pa)
                if isinstance(saved_pa, int): pa_id = saved_pa
                elif hasattr(saved_pa, 'id'): pa_id = saved_pa.id

        return s_id, d_id, pa_id, pa_gain_total
