import logging
import sqlite3
import json
from typing import List, Optional

from core.models.base_models import Sensor, Datalogger, PoleZero, Operator, ResponseFilter, Preamplifier, AnalogStage
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

class EquipmentDAO:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    # --- OPERATORS ---
    def get_all_operators(self) -> List[Operator]:
        query = "SELECT * FROM operator_catalog ORDER BY agency"
        operators = []
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query)
                for row in cursor.fetchall():
                    operators.append(Operator(**dict(row)))
            return operators
        except Exception as e:
            logger.error(f"Error retrieving operators: {e}")
            return []

    def save_operator(self, op: Operator) -> Optional[Operator]:
        """Unified method to insert or update an operator."""
        if op.id:
            return op if self.update_operator(op) else None
        return self.insert_operator(op)

    def insert_operator(self, op: Operator) -> Optional[Operator]:
        query = """INSERT INTO operator_catalog 
                   (agency, contact_name, contact_email, website, 
                    phone_country_code, phone_area_code, phone_number)  
                   VALUES (?, ?, ?, ?, ?, ?, ?)"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    op.agency, op.contact_name, op.contact_email, op.website,
                    op.phone_country_code, op.phone_area_code, op.phone_number
                ))
                conn.commit()
                op.id = cursor.lastrowid
                return op
        except Exception as e:
            logger.error(f"Error inserting operator: {e}")
            return None
    
    def update_operator(self, op: Operator) -> bool:
        query = """UPDATE operator_catalog 
                   SET agency=?, contact_name=?, contact_email=?, website=?, 
                       phone_country_code=?, phone_area_code=?, phone_number=? 
                   WHERE id=?"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    op.agency, op.contact_name, op.contact_email, op.website,
                    op.phone_country_code, op.phone_area_code, op.phone_number, op.id
                ))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating operator: {e}")
            return False

    def get_operator_by_agency(self, agency: str) -> Optional[Operator]:
        """Return the first operator whose agency matches (trimmed, case-insensitive)."""
        if not agency or not str(agency).strip():
            return None
        query = """
            SELECT * FROM operator_catalog
            WHERE LOWER(TRIM(agency)) = LOWER(TRIM(?))
            ORDER BY id ASC
            LIMIT 1
        """
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (agency.strip(),))
                row = cursor.fetchone()
                return Operator(**dict(row)) if row else None
        except Exception as e:
            logger.error("Error get_operator_by_agency(%r): %s", agency, e)
            return None

    def get_operator_by_id(self, op_id: int) -> Optional[Operator]:
        query = "SELECT * FROM operator_catalog WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (op_id,))
                row = cursor.fetchone()
                return Operator(**dict(row)) if row else None
        except Exception as e:
            logger.error("get_operator_by_id(%s): %s", op_id, e)
            return None

    def replace_operator(self, old_id: int, new_id: int) -> bool:
        """Reassigns networks and stations to new_id, then removes the old catalog row."""
        if old_id == new_id:
            return False
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE network SET operator_id = ? WHERE operator_id = ?", (new_id, old_id))
                cursor.execute("UPDATE station SET operator_id = ? WHERE operator_id = ?", (new_id, old_id))
                cursor.execute("DELETE FROM operator_catalog WHERE id = ?", (old_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted
        except Exception as e:
            logger.error("replace_operator(%s -> %s): %s", old_id, new_id, e)
            return False

    # --- SENSORS ---
    def _sensor_from_row(self, cursor: sqlite3.Cursor, row: sqlite3.Row) -> Sensor:
        """Builds a Sensor model from sensor_catalog row + child pole/zero tables."""
        sensor = Sensor(
            id=row["id"],
            manufacturer=row["manufacturer"] or "UNKNOWN",
            model=row["model"] or "UNKNOWN",
            type=row["type"],
            description=row["description"],
            sensitivity=float(row["sensitivity"]) if row["sensitivity"] is not None else 0.0,
            frequency=float(row["frequency"]) if row["frequency"] is not None else 1.0,
            normalization_factor=float(row["normalization_factor"])
            if row["normalization_factor"] is not None
            else 1.0,
            normalization_freq=float(row["normalization_freq"]) if row["normalization_freq"] is not None else 1.0,
            input_units=row["input_units"] or "m/s",
            output_units=row["output_units"] or "V",
            pz_transfer_function_type=row["pz_transfer_function_type"] or "LAPLACE (RADIANS/SECOND)",
            nrl_path=row["nrl_path"],
        )
        cursor.execute(
            "SELECT real_val, imag_val FROM sensor_zero WHERE sensor_id = ?",
            (sensor.id,),
        )
        sensor.zeros = [
            PoleZero(real_val=z["real_val"], imag_val=z["imag_val"]) for z in cursor.fetchall()
        ]
        cursor.execute(
            "SELECT real_val, imag_val FROM sensor_pole WHERE sensor_id = ?",
            (sensor.id,),
        )
        sensor.poles = [
            PoleZero(real_val=p["real_val"], imag_val=p["imag_val"]) for p in cursor.fetchall()
        ]
        return sensor

    def get_sensor_by_id(self, sensor_id: int) -> Optional[Sensor]:
        """Single sensor by primary key (poles/zeros included)."""
        query = "SELECT * FROM sensor_catalog WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (sensor_id,))
                row = cursor.fetchone()
                return self._sensor_from_row(cursor, row) if row else None
        except Exception as e:
            logger.error("get_sensor_by_id(%s): %s", sensor_id, e)
            return None

    def get_all_sensors(self) -> List[Sensor]:
        """Retrieves all sensors from the catalog with NULL-safe numeric conversion."""
        query_sensor = "SELECT * FROM sensor_catalog ORDER BY manufacturer, model"
        sensors = []
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query_sensor)
                for row in cursor.fetchall():
                    sensors.append(self._sensor_from_row(cursor, row))
            return sensors
        except Exception as e:
            logger.error(f"Error retrieving sensors: {e}")
            return []

    def get_sensors_with_nrl_path(self) -> List[Sensor]:
        """Sensors whose catalog row has a non-empty NRL path (SQL filter, no full-table scan in app code)."""
        query_sensor = """
            SELECT * FROM sensor_catalog
            WHERE nrl_path IS NOT NULL AND TRIM(nrl_path) != ''
            ORDER BY manufacturer, model
        """
        sensors: List[Sensor] = []
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query_sensor)
                for row in cursor.fetchall():
                    sensors.append(self._sensor_from_row(cursor, row))
            return sensors
        except Exception as e:
            logger.error("get_sensors_with_nrl_path: %s", e)
            return []
            
    def save_sensor(self, sensor: Sensor) -> Optional[Sensor]:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # Prepare nrl_path safely
                s_nrl_path = getattr(sensor, 'nrl_path', None)
                
                if getattr(sensor, 'id', None):
                    # If it exists, update it
                    cursor.execute("""
                        UPDATE sensor_catalog 
                        SET manufacturer=?, model=?, type=?, description=?, sensitivity=?, 
                            frequency=?, normalization_factor=?, normalization_freq=?, 
                            input_units=?, output_units=?, pz_transfer_function_type=?, nrl_path=?
                        WHERE id=?
                    """, (sensor.manufacturer, sensor.model, sensor.type, sensor.description,
                          sensor.sensitivity, sensor.frequency, sensor.normalization_factor,
                          sensor.normalization_freq, sensor.input_units, sensor.output_units,
                          sensor.pz_transfer_function_type, s_nrl_path, sensor.id))
                    
                    cursor.execute("DELETE FROM sensor_zero WHERE sensor_id=?", (sensor.id,))
                    cursor.execute("DELETE FROM sensor_pole WHERE sensor_id=?", (sensor.id,))
                else:
                    # Insertion
                    cursor.execute("""
                        INSERT INTO sensor_catalog 
                        (manufacturer, model, type, description, sensitivity, frequency, 
                         normalization_factor, normalization_freq, input_units, output_units, pz_transfer_function_type, nrl_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (sensor.manufacturer, sensor.model, sensor.type, sensor.description,
                          sensor.sensitivity, sensor.frequency, sensor.normalization_factor,
                          sensor.normalization_freq, sensor.input_units, sensor.output_units,
                          sensor.pz_transfer_function_type, s_nrl_path))
                    sensor.id = cursor.lastrowid
                
                if hasattr(sensor, 'zeros') and sensor.zeros:
                    for z in sensor.zeros:
                        cursor.execute("INSERT INTO sensor_zero (sensor_id, real_val, imag_val) VALUES (?, ?, ?)",
                                       (sensor.id, z.real_val, z.imag_val))
                if hasattr(sensor, 'poles') and sensor.poles:
                    for p in sensor.poles:
                        cursor.execute("INSERT INTO sensor_pole (sensor_id, real_val, imag_val) VALUES (?, ?, ?)",
                                       (sensor.id, p.real_val, p.imag_val))
                conn.commit()
                return sensor
        except Exception as e:
            logger.error(f"Error saving sensor: {e}")
            return None

    def insert_sensor(self, s: Sensor) -> Optional[Sensor]:
        query = """INSERT INTO sensor_catalog 
                   (manufacturer, model, type, description, sensitivity, frequency, 
                    normalization_factor, normalization_freq, input_units, output_units,
                    pz_transfer_function_type, nrl_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (s.manufacturer, s.model, s.type, s.description, s.sensitivity,
                                     s.frequency, s.normalization_factor, s.normalization_freq,
                                     s.input_units, s.output_units, s.pz_transfer_function_type, getattr(s, 'nrl_path', None)))
                s.id = cursor.lastrowid
                for z in s.zeros:
                    cursor.execute("INSERT INTO sensor_zero (sensor_id, real_val, imag_val) VALUES (?,?,?)", (s.id, z.real_val, z.imag_val))
                for p in s.poles:
                    cursor.execute("INSERT INTO sensor_pole (sensor_id, real_val, imag_val) VALUES (?,?,?)", (s.id, p.real_val, p.imag_val))
                conn.commit(); return s
        except Exception as e:
            logger.error(f"Error inserting sensor: {e}"); return None

    def update_sensor(self, s: Sensor) -> bool:
        query = """UPDATE sensor_catalog SET 
                   manufacturer=?, model=?, type=?, description=?, sensitivity=?, frequency=?, 
                   normalization_factor=?, normalization_freq=?, input_units=?, output_units=?,
                   pz_transfer_function_type=?, nrl_path=? WHERE id=?"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (s.manufacturer, s.model, s.type, s.description, s.sensitivity,
                                     s.frequency, s.normalization_factor, s.normalization_freq,
                                     s.input_units, s.output_units, s.pz_transfer_function_type, getattr(s, 'nrl_path', None), s.id))
                cursor.execute("DELETE FROM sensor_zero WHERE sensor_id=?", (s.id,))
                cursor.execute("DELETE FROM sensor_pole WHERE sensor_id=?", (s.id,))
                for z in s.zeros:
                    cursor.execute("INSERT INTO sensor_zero (sensor_id, real_val, imag_val) VALUES (?,?,?)", (s.id, z.real_val, z.imag_val))
                for p in s.poles:
                    cursor.execute("INSERT INTO sensor_pole (sensor_id, real_val, imag_val) VALUES (?,?,?)", (s.id, p.real_val, p.imag_val))
                conn.commit(); return True
        except Exception as e:
            logger.error(f"Error updating sensor: {e}"); return False

    # --- DATALOGGER ---
    def _datalogger_from_row(self, cursor: sqlite3.Cursor, row: sqlite3.Row) -> Datalogger:
        """Builds a Datalogger from datalogger_catalog row + filter stages."""
        dl = Datalogger(
            id=row["id"],
            manufacturer=row["manufacturer"] or "UNKNOWN",
            model=row["model"] or "UNKNOWN",
            description=row["description"],
            gain=float(row["gain"]) if row["gain"] is not None else 1.0,
            max_clock_drift=float(row["max_clock_drift"]) if row["max_clock_drift"] is not None else 0.0,
            base_hardware_delay=float(row["base_hardware_delay"])
            if row["base_hardware_delay"] is not None
            else 0.0,
            base_hardware_correction=float(row["base_hardware_correction"])
            if row["base_hardware_correction"] is not None
            else 0.0,
            nrl_path=row["nrl_path"],
        )
        cursor.execute(
            "SELECT * FROM datalogger_filter WHERE datalogger_id = ? ORDER BY stage_number",
            (dl.id,),
        )
        for f_row in cursor.fetchall():
            f_dict = dict(f_row)
            f_dict.pop("datalogger_id", None)
            f_id = f_dict.pop("id", None)
            dl.filters.append(
                ResponseFilter(
                    id=f_id,
                    stage_number=f_dict["stage_number"],
                    filter_type=f_dict["filter_type"],
                    coefficients=f_dict["coefficients"],
                    decimation_factor=f_dict["decimation_factor"] or 1,
                    input_sample_rate=float(f_dict["input_sample_rate"])
                    if f_dict["input_sample_rate"] is not None
                    else 0.0,
                    output_sample_rate=float(f_dict["output_sample_rate"])
                    if f_dict["output_sample_rate"] is not None
                    else 0.0,
                    estimated_delay=float(f_dict["estimated_delay"])
                    if f_dict["estimated_delay"] is not None
                    else 0.0,
                    correction_applied=float(f_dict["correction_applied"])
                    if f_dict["correction_applied"] is not None
                    else 0.0,
                )
            )
        return dl

    def get_datalogger_by_id(self, datalogger_id: int) -> Optional[Datalogger]:
        """Single datalogger by primary key (filters included)."""
        query = "SELECT * FROM datalogger_catalog WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (datalogger_id,))
                row = cursor.fetchone()
                return self._datalogger_from_row(cursor, row) if row else None
        except Exception as e:
            logger.error("get_datalogger_by_id(%s): %s", datalogger_id, e)
            return None

    def get_all_dataloggers(self) -> List[Datalogger]:
        """Retrieves all dataloggers with NULL-safe numeric conversion."""
        query_dl = "SELECT * FROM datalogger_catalog ORDER BY manufacturer, model"
        dataloggers = []
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query_dl)
                for row in cursor.fetchall():
                    dataloggers.append(self._datalogger_from_row(cursor, row))
            return dataloggers
        except Exception as e:
            logger.error(f"Error retrieving dataloggers: {e}")
            return []

    def get_dataloggers_with_nrl_path(self) -> List[Datalogger]:
        """Dataloggers with non-empty NRL path (SQL filter)."""
        query_dl = """
            SELECT * FROM datalogger_catalog
            WHERE nrl_path IS NOT NULL AND TRIM(nrl_path) != ''
            ORDER BY manufacturer, model
        """
        dataloggers: List[Datalogger] = []
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query_dl)
                for row in cursor.fetchall():
                    dataloggers.append(self._datalogger_from_row(cursor, row))
            return dataloggers
        except Exception as e:
            logger.error("get_dataloggers_with_nrl_path: %s", e)
            return []

    def save_datalogger(self, dl: Datalogger) -> Optional[Datalogger]:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                dl_nrl_path = getattr(dl, 'nrl_path', None)
                
                if getattr(dl, 'id', None):
                    cursor.execute("""
                        UPDATE datalogger_catalog 
                        SET manufacturer=?, model=?, description=?, gain=?, 
                            max_clock_drift=?, base_hardware_delay=?, base_hardware_correction=?, nrl_path=?
                        WHERE id=?
                    """, (dl.manufacturer, dl.model, dl.description, dl.gain,
                          dl.max_clock_drift, dl.base_hardware_delay, dl.base_hardware_correction, dl_nrl_path, dl.id))
                    
                    cursor.execute("DELETE FROM datalogger_filter WHERE datalogger_id=?", (dl.id,))
                else:
                    cursor.execute("""
                        INSERT INTO datalogger_catalog 
                        (manufacturer, model, description, gain, max_clock_drift, 
                         base_hardware_delay, base_hardware_correction, nrl_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (dl.manufacturer, dl.model, dl.description, dl.gain,
                          dl.max_clock_drift, dl.base_hardware_delay, dl.base_hardware_correction, dl_nrl_path))
                    dl.id = cursor.lastrowid
                
                if hasattr(dl, 'filters') and dl.filters:
                    for f in dl.filters:
                        cursor.execute("""
                            INSERT INTO datalogger_filter 
                            (datalogger_id, stage_number, filter_type, coefficients, decimation_factor, 
                             input_sample_rate, output_sample_rate, estimated_delay, correction_applied)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (dl.id, getattr(f, 'stage_number', 0), getattr(f, 'filter_type', 'FIR'),
                              getattr(f, 'coefficients', '[]'), getattr(f, 'decimation_factor', 1),
                              getattr(f, 'input_sample_rate', 0.0), getattr(f, 'output_sample_rate', 0.0),
                              getattr(f, 'estimated_delay', 0.0), getattr(f, 'correction_applied', 0.0)))
                conn.commit()
                return dl
        except Exception as e:
            logger.error(f"Error saving datalogger: {e}")
            return None

    def insert_datalogger(self, dl: Datalogger) -> Optional[Datalogger]:
        query = """INSERT INTO datalogger_catalog 
                   (manufacturer, model, description, gain, 
                    max_clock_drift, base_hardware_delay, base_hardware_correction, nrl_path) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    dl.manufacturer, dl.model, dl.description,
                    dl.gain, dl.max_clock_drift,
                    getattr(dl, 'base_hardware_delay', 0.0),
                    getattr(dl, 'base_hardware_correction', 0.0),
                    getattr(dl, 'nrl_path', None)
                ))
                dl.id = cursor.lastrowid
                for f in dl.filters:
                    cursor.execute("""INSERT INTO datalogger_filter 
                        (datalogger_id, stage_number, filter_type, coefficients, 
                         decimation_factor, input_sample_rate, output_sample_rate,
                         estimated_delay, correction_applied)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (dl.id, f.stage_number, f.filter_type, f.coefficients,
                         f.decimation_factor, f.input_sample_rate, f.output_sample_rate,
                         f.estimated_delay, f.correction_applied))
                conn.commit()
                return dl
        except Exception as e:
            logger.error(f"Error inserting datalogger {dl.model}: {e}"); return None

    def update_datalogger(self, dl: Datalogger) -> bool:
        query = """UPDATE datalogger_catalog SET 
                   manufacturer=?, model=?, description=?, gain=?, 
                   max_clock_drift=?, base_hardware_delay=?, base_hardware_correction=?, nrl_path=? 
                   WHERE id=?"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    dl.manufacturer, dl.model, dl.description,
                    dl.gain, dl.max_clock_drift,
                    getattr(dl, 'base_hardware_delay', 0.0),
                    getattr(dl, 'base_hardware_correction', 0.0),
                    getattr(dl, 'nrl_path', None),
                    dl.id
                ))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating datalogger {dl.model}: {e}"); return False
   
    # --- OTHER METHODS ---
    def count_channels_using_sensor(self, sensor_id: int) -> int:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM channel WHERE sensor_id = ?", (sensor_id,))
                return int(cursor.fetchone()[0])
        except Exception as e:
            logger.error("count_channels_using_sensor: %s", e)
            return 0

    def count_channels_using_datalogger(self, datalogger_id: int) -> int:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM channel WHERE datalogger_id = ?", (datalogger_id,))
                return int(cursor.fetchone()[0])
        except Exception as e:
            logger.error("count_channels_using_datalogger: %s", e)
            return 0

    def get_equipment_summary_counts(self) -> tuple[int, int, int, int]:
        """
        Returns (total_sensors, total_dataloggers, sensors_in_channels, dataloggers_in_channels).
        *_in_channels = distinct catalog IDs referenced by at least one channel (inner join).
        """
        sql = """
            SELECT
                (SELECT COUNT(*) FROM sensor_catalog) AS total_sensors,
                (SELECT COUNT(*) FROM datalogger_catalog) AS total_dataloggers,
                (SELECT COUNT(DISTINCT c.sensor_id) FROM channel c
                 INNER JOIN sensor_catalog s ON s.id = c.sensor_id
                 WHERE c.sensor_id IS NOT NULL) AS sensors_in_channels,
                (SELECT COUNT(DISTINCT c.datalogger_id) FROM channel c
                 INNER JOIN datalogger_catalog d ON d.id = c.datalogger_id
                 WHERE c.datalogger_id IS NOT NULL) AS dataloggers_in_channels
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                row = cursor.fetchone()
                if not row:
                    return 0, 0, 0, 0
                return (
                    int(row[0]),
                    int(row[1]),
                    int(row[2]),
                    int(row[3]),
                )
        except Exception as e:
            logger.error("get_equipment_summary_counts: %s", e)
            return 0, 0, 0, 0

    def delete_sensor(self, sensor_id: int) -> bool:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM channel WHERE sensor_id = ?", (sensor_id,))
                n = int(cursor.fetchone()[0])
                if n > 0:
                    raise ValueError(
                        f"Cannot delete sensor: {n} channel(s) in the inventory still reference it "
                        "(StationXML / DB). Remove or reassign those channels first."
                    )
                cursor.execute("DELETE FROM sensor_catalog WHERE id = ?", (sensor_id,))
                conn.commit()
                return cursor.rowcount > 0
        except ValueError:
            raise
        except Exception as e:
            logger.error("delete_sensor: %s", e)
            raise

    def delete_datalogger(self, datalogger_id: int) -> bool:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM channel WHERE datalogger_id = ?", (datalogger_id,))
                n = int(cursor.fetchone()[0])
                if n > 0:
                    raise ValueError(
                        f"Cannot delete datalogger: {n} channel(s) in the inventory still reference it "
                        "(StationXML / DB). Remove or reassign those channels first."
                    )
                cursor.execute("DELETE FROM datalogger_catalog WHERE id = ?", (datalogger_id,))
                conn.commit()
                return cursor.rowcount > 0
        except ValueError:
            raise
        except Exception as e:
            logger.error("delete_datalogger: %s", e)
            raise

    def delete_operator(self, op_id: int) -> bool:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM network WHERE operator_id = ?", (op_id,))
                if cursor.fetchone()[0] > 0: raise ValueError("Cannot delete: Operator is used in a Network!")
                cursor.execute("DELETE FROM operator_catalog WHERE id = ?", (op_id,))
                conn.commit(); return True
        except Exception as e: raise e
            
    def get_operator_by_details(self, agency: str, contact_name: str, contact_email: str) -> Optional[Operator]:
        query = "SELECT * FROM operator_catalog WHERE agency = ? AND contact_name IS ? AND contact_email IS ?"
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (agency, contact_name, contact_email))
                row = cursor.fetchone()
                return Operator(**dict(row)) if row else None
        except Exception as e:
            logger.error(f"Error searching for operator: {e}")
            return None
            
    # ==========================================
    # --- PREAMPLIFIERS MANAGEMENT (MULTI-STAGE) ---
    # ==========================================

    def get_all_preamplifiers(self) -> List[Preamplifier]:
        """Retrieves all preamplifiers with their internal analog stages."""
        query = "SELECT * FROM preamplifier_catalog ORDER BY model"
        preamps = []
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query)
                for row in cursor.fetchall():
                    preamps.append(self._row_to_preamp(row, cursor))
            return preamps
        except Exception as e:
            logger.error(f"Error retrieving preamplifiers: {e}")
            return []
    
    def get_preamplifier_by_id(self, preamp_id: int) -> Optional[Preamplifier]:
        """Retrieves a single preamplifier by ID."""
        query = "SELECT * FROM preamplifier_catalog WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (preamp_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_preamp(row, cursor)
        except Exception as e:
            logger.error(f"Error retrieving preamplifier {preamp_id}: {e}")
        return None

    def save_preamplifier(self, preamp: Preamplifier) -> Optional[Preamplifier]:
        """Saves or updates a preamplifier and its cascade of analog stages."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Insert or Update base catalog
                if preamp.id is None:
                    cursor.execute("""
                        INSERT INTO preamplifier_catalog (manufacturer, model, description, type)
                        VALUES (?, ?, ?, 'PRE-AMPLIFIER')
                    """, (preamp.manufacturer, preamp.model, preamp.description))
                    preamp.id = cursor.lastrowid
                else:
                    cursor.execute("""
                        UPDATE preamplifier_catalog 
                        SET manufacturer=?, model=?, description=? 
                        WHERE id=?
                    """, (preamp.manufacturer, preamp.model, preamp.description, preamp.id))
                    
                    # Cleanup old stages (SQL CASCADE will automatically clean poles and zeros too)
                    cursor.execute("DELETE FROM preamplifier_stage WHERE preamplifier_id = ?", (preamp.id,))
                
                # 2. Insert the new cascade of stages
                for stage in preamp.analog_stages:
                    cursor.execute("""
                        INSERT INTO preamplifier_stage 
                        (preamplifier_id, stage_sequence, stage_gain, input_units, output_units, name)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (preamp.id, stage.stage_sequence, stage.stage_gain, stage.input_units, stage.output_units, stage.name))
                    stage_id = cursor.lastrowid
                    
                    # Insert stage Poles
                    for p in stage.poles:
                        cursor.execute("INSERT INTO preamplifier_stage_pole (stage_id, real_val, imag_val) VALUES (?, ?, ?)",
                                       (stage_id, p.real_val, p.imag_val))
                    
                    # Insert stage Zeros
                    for z in stage.zeros:
                        cursor.execute("INSERT INTO preamplifier_stage_zero (stage_id, real_val, imag_val) VALUES (?, ?, ?)",
                                       (stage_id, z.real_val, z.imag_val))
                
                conn.commit()
                return preamp
        except Exception as e:
            logger.error(f"Error saving preamplifier {preamp.model}: {e}")
            return None
            
    def delete_preamplifier(self, preamp_id: int) -> bool:
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                # Check if in use
                cursor.execute("SELECT COUNT(*) FROM channel WHERE pre_amplifier_id = ?", (preamp_id,))
                if cursor.fetchone()[0] > 0:
                    raise ValueError("Cannot delete: Preamplifier is in use in one or more channels!")
                
                cursor.execute("DELETE FROM preamplifier_catalog WHERE id = ?", (preamp_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error deleting preamplifier: {e}")
            raise e
            
    def _row_to_preamp(self, row, cursor) -> Preamplifier:
        """Internal helper to map from DB to Preamplifier class with sanitized Stages."""
        preamp_id = row['id']
        preamp = Preamplifier(
            id=preamp_id,
            manufacturer=row['manufacturer'] or "UNKNOWN",
            model=row['model'] or "UNKNOWN",
            description=row['description']
        )
        
        cursor.execute("SELECT * FROM preamplifier_stage WHERE preamplifier_id = ? ORDER BY stage_sequence", (preamp_id,))
        for s_row in cursor.fetchall():
            stage = AnalogStage(
                id=s_row['id'],
                stage_sequence=s_row['stage_sequence'],
                stage_gain=float(s_row['stage_gain']) if s_row['stage_gain'] is not None else 1.0,
                input_units=s_row['input_units'] or "V",
                output_units=s_row['output_units'] or "V",
                name=s_row['name'] or f"Stage {s_row['stage_sequence']}"
            )
            
            cursor.execute("SELECT real_val, imag_val FROM preamplifier_stage_pole WHERE stage_id = ?", (stage.id,))
            stage.poles = [PoleZero(real_val=p['real_val'], imag_val=p['imag_val']) for p in cursor.fetchall()]
            
            cursor.execute("SELECT real_val, imag_val FROM preamplifier_stage_zero WHERE stage_id = ?", (stage.id,))
            stage.zeros = [PoleZero(real_val=z['real_val'], imag_val=z['imag_val']) for z in cursor.fetchall()]
            
            preamp.analog_stages.append(stage)
            
        return preamp

    def replace_equipment(self, category: str, old_id: int, new_id: int) -> bool:
        """
        Replaces one equipment with another in all channels, 
        recalculates total channel sensitivity, and then deletes the old instrument.
        """
        mapping = {
            'sensor': ('sensor_catalog', 'sensor_id'),
            'datalogger': ('datalogger_catalog', 'datalogger_id'),
            'preamplifier': ('preamplifier_catalog', 'pre_amplifier_id')
        }
        
        if category not in mapping:
            return False
            
        table_name, channel_col = mapping[category]

        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # 1. Move all channels to the new instrument
                cursor.execute(f"UPDATE channel SET {channel_col} = ? WHERE {channel_col} = ?", (new_id, old_id))
                
                # 2. SENSITIVITY RECALCULATION FOR INVOLVED CHANNELS
                cursor.execute(f"SELECT id, sensor_id, datalogger_id, pre_amplifier_id FROM channel WHERE {channel_col} = ?", (new_id,))
                affected_channels = cursor.fetchall()
                
                for ch in affected_channels:
                    total_sens = 1.0
                    
                    if ch['sensor_id']:
                        s_res = cursor.execute("SELECT sensitivity FROM sensor_catalog WHERE id = ?", (ch['sensor_id'],)).fetchone()
                        if s_res and s_res['sensitivity'] is not None:
                            total_sens *= float(s_res['sensitivity'])
                            
                    if ch['pre_amplifier_id']:
                        p_stages = cursor.execute("SELECT stage_gain FROM preamplifier_stage WHERE preamplifier_id = ?", (ch['pre_amplifier_id'],)).fetchall()
                        for stage_row in p_stages:
                            if stage_row['stage_gain'] is not None:
                                total_sens *= float(stage_row['stage_gain'])

                    if ch['datalogger_id']:
                        d_res = cursor.execute("SELECT gain FROM datalogger_catalog WHERE id = ?", (ch['datalogger_id'],)).fetchone()
                        if d_res and d_res['gain'] is not None:
                            total_sens *= float(d_res['gain'])
                            
                    cursor.execute("UPDATE channel SET overall_sensitivity = ? WHERE id = ?", (total_sens, ch['id']))
                    
                # 3. Delete old record from catalog
                cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (old_id,))
                conn.commit()
                
                logger.info(f"Merge & Replace completed for {category}: {old_id} -> {new_id}. Sensitivity recalculated for {len(affected_channels)} channels.")
                return True
                
        except Exception as e:
            logger.error(f"Error during Merge & Replace of {category}: {e}")
            return False
