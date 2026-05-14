import sqlite3
import logging
from typing import List, Optional

from core.models.base_models import Station
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

class StationDAO:
    """
    Data Access Object for the 'station' table.
    Manages CRUD operations including Creation Date, Operator ID, Vault, Geology and 100% FDSN fields.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_by_network_id(self, network_id: int) -> List[Station]:
        """
        Retrieves all child stations of a specific network.
        """
        query = """
            SELECT s.*, y.local_xml_hash as sync_hash, y.yasmine_node_id 
            FROM station s 
            LEFT JOIN yasmine_sync_state y ON s.id = y.station_id 
            WHERE s.network_id = ? 
            ORDER BY s.code
        """
        stations = []
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (network_id,))
                
                for row in cursor.fetchall():
                    stations.append(self._row_to_model(row))
        except sqlite3.Error as e:
            logger.error(f"Error retrieving stations for network {network_id}: {e}")
            
        return stations

    def get_by_id(self, station_id: int) -> Optional[Station]:
        """Retrieves a single station by its ID."""
        query = """
            SELECT s.*, y.local_xml_hash as sync_hash, y.yasmine_node_id 
            FROM station s 
            LEFT JOIN yasmine_sync_state y ON s.id = y.station_id 
            WHERE s.id = ?
        """
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (station_id,))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_model(row)
        except sqlite3.Error as e:
            logger.error(f"Error retrieving station with ID {station_id}: {e}")
            
        return None

    def insert(self, station: Station) -> Station:
        """Inserts a new station."""
        query = """
            INSERT INTO station (
                network_id, code, latitude, longitude, elevation,
                site_name, start_date, end_date, creation_date, operator_id,
                vault, geology, restricted_status,
                water_level, description, town, county, region, country, comments
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    station.network_id, station.code, station.latitude, station.longitude,
                    station.elevation, station.site_name, station.start_date,
                    station.end_date, station.creation_date, station.operator_id,
                    station.vault, station.geology, station.restricted_status,
                    station.water_level, station.description, station.town,
                    station.county, station.region, station.country,
                    station.comments
                ))
                conn.commit()
                
                station.id = cursor.lastrowid
                logger.info(f"Station {station.code} inserted with ID {station.id}.")
                
        except sqlite3.IntegrityError as e:
            logger.warning(f"Integrity violation for station {station.code}: {e}")
            raise
        except sqlite3.Error as e:
            logger.error(f"Error inserting station {station.code}: {e}")
            raise
            
        return station

    def update(self, station: Station) -> bool:
        """Updates data for an existing station."""
        if station.id is None:
            return False
            
        query = """
            UPDATE station SET
                code=?, latitude=?, longitude=?, elevation=?, site_name=?,
                start_date=?, end_date=?, creation_date=?, operator_id=?,
                vault=?, geology=?, restricted_status=?,
                water_level=?, description=?, town=?, county=?, region=?, country=?, comments=?
            WHERE id=?
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    station.code, station.latitude, station.longitude, station.elevation,
                    station.site_name, station.start_date, station.end_date,
                    station.creation_date, station.operator_id, station.vault,
                    station.geology, station.restricted_status,
                    station.water_level, station.description, station.town,
                    station.county, station.region, station.country,
                    station.comments,
                    station.id
                ))
                conn.commit()
                return cursor.rowcount > 0
                
        except sqlite3.Error as e:
            logger.error(f"Error updating station ID {station.id}: {e}")
            return False

    def delete(self, station_id: int) -> bool:
        """Deletes a station (associated channels will be deleted via SQLite cascade)."""
        query = "DELETE FROM station WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (station_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error deleting station ID {station_id}: {e}")
            return False

    def _row_to_model(self, row: sqlite3.Row) -> Station:
        """Helper to map an SQLite row to a Station object."""
        latitude = row["latitude"] if row["latitude"] is not None else 0.0
        longitude = row["longitude"] if row["longitude"] is not None else 0.0
        elevation = row["elevation"] if row["elevation"] is not None else 0.0
        water_level = row["water_level"] if row["water_level"] is not None else 0.0

        station = Station(
            id=row['id'],
            network_id=row['network_id'],
            code=row['code'],
            latitude=latitude,
            longitude=longitude,
            elevation=elevation,
            site_name=row['site_name'],
            start_date=row['start_date'],
            end_date=row['end_date'],
            creation_date=row['creation_date'],
            operator_id=row['operator_id'],
            vault=row['vault'],
            geology=row['geology'],
            restricted_status=row['restricted_status'],
            water_level=water_level,
            description=row['description'],
            town=row['town'],
            county=row['county'],
            region=row['region'],
            country=row['country'],
            comments=row['comments'] if 'comments' in row.keys() else None
        )
        
        # Le righe che causavano il crash di Pydantic sono state rimosse da qui.
            
        return station
        
    def get_sync_state(self, station_id: int) -> Optional[sqlite3.Row]:
        """Retrieves the synchronization state of a station with Yasmine."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT yasmine_node_id, local_xml_hash, sync_timestamp FROM yasmine_sync_state WHERE station_id = ?",
                    (station_id,)
                )
                return cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Error retrieving sync_state for station {station_id}: {e}")
            return None

    def upsert_sync_state(self, station_id: int, yasmine_node_id: str, local_xml_hash: str) -> bool:
        """Inserts or updates the synchronization state on Yasmine."""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO yasmine_sync_state (station_id, yasmine_node_id, local_xml_hash, sync_timestamp)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(station_id) 
                    DO UPDATE SET 
                        yasmine_node_id=excluded.yasmine_node_id,
                        local_xml_hash=excluded.local_xml_hash,
                        sync_timestamp=CURRENT_TIMESTAMP
                ''', (station_id, yasmine_node_id, local_xml_hash))
                conn.commit()
                return True
        except sqlite3.Error as e:
            logger.error(f"Error updating sync_state for station_id {station_id}: {e}")
            return False
    
    def update_sync_hash(self, station_id: int, new_hash: str) -> bool:
        """
        Updates the hash to invalidate synchronization (Red Traffic Light).
        """
        query = "UPDATE yasmine_sync_state SET local_xml_hash = ? WHERE station_id = ?"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (new_hash, station_id))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error updating hash for station {station_id}: {e}")
            return False
            
    def get_all_stations(self) -> List[Station]:
        """Retrieves all stations present in the database."""
        query = "SELECT * FROM station"
        stations = []
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                for row in cursor.fetchall():
                    stations.append(self._row_to_model(row))
        except sqlite3.Error as e:
            logger.error(f"Error retrieving all stations: {e}")
        return stations
    
    def get_all(self) -> List[Station]:
        """Retrieves all stations in the entire archive including Yasmine state."""
        # LEFT JOIN to get station data + Yasmine hash
        query = """
            SELECT s.*, y.local_xml_hash as sync_hash, y.yasmine_node_id 
            FROM station s 
            LEFT JOIN yasmine_sync_state y ON s.id = y.station_id 
            ORDER BY s.code
        """
        stations = []
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                for row in cursor.fetchall():
                    stations.append(self._row_to_model(row))
        except sqlite3.Error as e:
            logger.error(f"Error during global retrieval of stations: {e}")
        return stations
