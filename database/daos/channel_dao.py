import sqlite3
import logging
from typing import List, Optional

from core.models.base_models import Channel
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

class ChannelDAO:
    """
    Data Access Object for the 'channel' table.
    Manages CRUD operations aligned with the FDSN standard and the new scientific logic.
    """
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_by_station_id(self, station_id: int) -> List[Channel]:
        query = "SELECT * FROM channel WHERE station_id = ? ORDER BY code, location_code"
        channels = []
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (station_id,))
                for row in cursor.fetchall():
                    channels.append(self._row_to_model(row))
        except sqlite3.Error as e:
            logger.error(f"Error retrieving channels for station {station_id}: {e}")
        return channels

    def get_by_id(self, channel_id: int) -> Optional[Channel]:
        query = "SELECT * FROM channel WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (channel_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_model(row)
                return None
        except Exception as e:
            logger.error(f"Error retrieving channel {channel_id}: {e}")
            return None

    def insert(self, channel: Channel) -> Optional[Channel]:
        """Inserts a new channel. Note: removed useless delay/correction variables."""
        query = """
            INSERT INTO channel (
                station_id, code, location_code, latitude, longitude, elevation,
                depth, sample_rate, azimuth, dip, sensor_id, 
                datalogger_id, start_date, end_date, overall_sensitivity,
                sensor_serial_number, datalogger_serial_number, types,
                clock_drift, calibration_units, pre_amplifier_id, 
                pre_amplifier_serial_number, pre_amplifier_gain, comments
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            channel.station_id, channel.code, channel.location_code,
            channel.latitude, channel.longitude, channel.elevation,
            channel.depth, channel.sample_rate, channel.azimuth,
            channel.dip, channel.sensor_id, channel.datalogger_id,
            channel.start_date, channel.end_date, channel.overall_sensitivity,
            channel.sensor_serial_number, channel.datalogger_serial_number,
            channel.types, channel.clock_drift, channel.calibration_units,
            channel.pre_amplifier_id, channel.pre_amplifier_serial_number,
            channel.pre_amplifier_gain, channel.comments
        )
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                channel.id = cursor.lastrowid
                return channel
        except Exception as e:
            logger.error(f"Error inserting channel {channel.code}: {e}")
            return None

    def update(self, channel: Channel) -> bool:
        """Updates channel data removing incorrect analog parameters."""
        query = """
            UPDATE channel SET 
                code=?, location_code=?, latitude=?, longitude=?, elevation=?,
                depth=?, sample_rate=?, azimuth=?, dip=?, sensor_id=?, 
                datalogger_id=?, start_date=?, end_date=?, overall_sensitivity=?,
                sensor_serial_number=?, datalogger_serial_number=?, types=?,
                clock_drift=?, calibration_units=?, pre_amplifier_id=?, 
                pre_amplifier_serial_number=?, pre_amplifier_gain=?, comments=?
            WHERE id=?
        """
        params = (
            channel.code, channel.location_code, channel.latitude,
            channel.longitude, channel.elevation, channel.depth,
            channel.sample_rate, channel.azimuth, channel.dip,
            channel.sensor_id, channel.datalogger_id,
            channel.start_date, channel.end_date, channel.overall_sensitivity,
            channel.sensor_serial_number, channel.datalogger_serial_number,
            channel.types, channel.clock_drift, channel.calibration_units,
            channel.pre_amplifier_id, channel.pre_amplifier_serial_number,
            channel.pre_amplifier_gain,
            channel.comments,
            channel.id
        )
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating channel ID {channel.id}: {e}")
            return False

    def delete(self, channel_id: int) -> bool:
        query = "DELETE FROM channel WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (channel_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting channel {channel_id}: {e}")
            return False
            
    def save_channel(self, channel: Channel) -> bool:
        try:
            query = """
                INSERT INTO channel (
                    station_id, code, location_code, start_date, end_date,
                    latitude, longitude, elevation, depth, azimuth, dip,
                    sample_rate, clock_drift,
                    sensor_id, datalogger_id, 
                    pre_amplifier_id, pre_amplifier_serial_number, pre_amplifier_gain, comments
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(station_id, code, location_code, start_date) DO UPDATE SET
                    end_date=excluded.end_date,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    elevation=excluded.elevation,
                    depth=excluded.depth,
                    azimuth=excluded.azimuth,
                    dip=excluded.dip,
                    sample_rate=excluded.sample_rate,
                    clock_drift=excluded.clock_drift,
                    sensor_id=excluded.sensor_id,
                    datalogger_id=excluded.datalogger_id,
                    pre_amplifier_id=excluded.pre_amplifier_id,
                    pre_amplifier_serial_number=excluded.pre_amplifier_serial_number,
                    pre_amplifier_gain=excluded.pre_amplifier_gain,
                    comments=excluded.comments
            """
            params = (
                channel.station_id, channel.code, channel.location_code,
                channel.start_date, channel.end_date,
                channel.latitude, channel.longitude, channel.elevation,
                channel.depth, channel.azimuth, channel.dip,
                channel.sample_rate, channel.clock_drift,
                channel.sensor_id, channel.datalogger_id,
                channel.pre_amplifier_id, channel.pre_amplifier_serial_number,
                channel.pre_amplifier_gain, channel.comments
            )
            with self.db.get_connection() as conn:
                conn.execute(query, params)
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving channel {channel.code}: {e}")
            return False

    def _row_to_model(self, row: sqlite3.Row) -> Optional[Channel]:
        """Converts a database row into a Channel dataclass object."""
        if not row:
            return None

        latitude = row["latitude"] if row["latitude"] is not None else 0.0
        longitude = row["longitude"] if row["longitude"] is not None else 0.0
        elevation = row["elevation"] if row["elevation"] is not None else 0.0
        depth = row["depth"] if row["depth"] is not None else 0.0
        azimuth = row["azimuth"] if row["azimuth"] is not None else 0.0
        dip = row["dip"] if row["dip"] is not None else 0.0
        sample_rate = row["sample_rate"] if row["sample_rate"] is not None else 0.0
        clock_drift = row["clock_drift"] if ("clock_drift" in row.keys() and row["clock_drift"] is not None) else 0.0
        pre_amplifier_gain = (
            row["pre_amplifier_gain"]
            if ("pre_amplifier_gain" in row.keys() and row["pre_amplifier_gain"] is not None)
            else 1.0
        )
        
        return Channel(
            id=row['id'],
            station_id=row['station_id'],
            code=row['code'],
            location_code=row['location_code'],
            latitude=latitude,
            longitude=longitude,
            elevation=elevation,
            depth=depth,
            azimuth=azimuth,
            dip=dip,
            sample_rate=sample_rate,
            start_date=row['start_date'],
            end_date=row['end_date'],
            sensor_id=row['sensor_id'],
            datalogger_id=row['datalogger_id'],
            overall_sensitivity=row['overall_sensitivity'],
            sensor_serial_number=row['sensor_serial_number'],
            datalogger_serial_number=row['datalogger_serial_number'],
            types=row['types'],
            clock_drift=clock_drift,
            calibration_units=row['calibration_units'] if 'calibration_units' in row.keys() else None,
            pre_amplifier_id=row['pre_amplifier_id'] if 'pre_amplifier_id' in row.keys() else None,
            pre_amplifier_serial_number=row['pre_amplifier_serial_number'] if 'pre_amplifier_serial_number' in row.keys() else None,
            pre_amplifier_gain=pre_amplifier_gain,
            comments = row['comments'] if 'comments' in row.keys() else None
        )