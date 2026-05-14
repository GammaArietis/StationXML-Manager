import sqlite3
import logging
from typing import List, Optional

from core.models.base_models import Network
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

class NetworkDAO:
    """
    Data Access Object for the 'network' table.
    Manages CRUD operations including DOI, Operator ID, and restricted_status.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def get_all(self) -> List[Network]:
        """Retrieves all networks."""
        query = "SELECT * FROM network ORDER BY code"
        networks = []
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                
                for row in cursor.fetchall():
                    networks.append(self._row_to_model(row))
        except sqlite3.Error as e:
            logger.error(f"Error retrieving networks: {e}")
            
        return networks

    def get_by_id(self, network_id: int) -> Optional[Network]:
        query = "SELECT * FROM network WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (network_id,))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_model(row)
        except sqlite3.Error as e:
            logger.error(f"Error retrieving network {network_id}: {e}")
            
        return None

    def delete(self, network_id: int) -> bool:
        """Deletes a network (automatic cascade on stations and channels)."""
        query = "DELETE FROM network WHERE id = ?"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (network_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error deleting network {network_id}: {e}")
            return False
    
    def insert(self, network: Network) -> Network:
        query = """
            INSERT INTO network (
                code, description, start_date, end_date, doi, operator_id, restricted_status, comments
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    network.code, network.description, network.start_date, network.end_date,
                    network.doi, network.operator_id, network.restricted_status, network.comments
                ))
                conn.commit()
                network.id = cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Error during insertion: {e}")
            raise
        return network

    def update(self, network: Network) -> bool:
        if network.id is None: return False
        query = """
            UPDATE network
            SET code=?, description=?, start_date=?, end_date=?, 
                doi=?, operator_id=?, restricted_status=?, comments=?
            WHERE id=?
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    network.code, network.description, network.start_date, network.end_date,
                    network.doi, network.operator_id, network.restricted_status, network.comments, network.id
                ))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error during update: {e}")
            return False

    def _row_to_model(self, row: sqlite3.Row) -> Network:
        restricted_status = row["restricted_status"] if row["restricted_status"] is not None else "open"
        return Network(
            id=row['id'], code=row['code'], description=row['description'],
            start_date=row['start_date'], end_date=row['end_date'],
            doi=row['doi'], operator_id=row['operator_id'],
            restricted_status=restricted_status,
            comments=row['comments'] if 'comments' in row.keys() else None
        )