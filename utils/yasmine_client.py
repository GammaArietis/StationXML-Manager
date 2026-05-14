import requests
import logging
from typing import Optional, List

from utils.logging_config import log_network_error

logger = logging.getLogger(__name__)

class YasmineClient:
    """
    Client for HTTP communication with Yasmine REST APIs (SCADA).
    Manages exploration, deletion, and uploading of StationXML files.
    """

    def __init__(self, base_url: Optional[str] = None):
        if base_url is None:
            from core.config import get_settings

            base_url = get_settings().yasmine_base_url
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/api/xml/"
        self.import_url = f"{self.base_url}/api/xml/ie/"
        
        # Cache to avoid repeatedly querying Yasmine
        # during operations that do not modify the server state.
        self._cached_list = None

    def get_all_files(self, force_refresh: bool = False) -> List[dict]:
        """
        Retrieves the list of all XML files present on Yasmine,
        using an internal cache to optimize performance.

        Args:
            force_refresh (bool): If True, ignores the cache and forces a download from the server.

        Returns:
            List[dict]: List of dictionaries containing file metadata.
        """
        if self._cached_list is None or force_refresh:
            try:
                response = requests.get(self.api_url, timeout=30)
                response.raise_for_status()
                self._cached_list = response.json()
            except Exception as e:
                log_network_error(logger, "Yasmine", e, detail="get_all_files")
                return []
        return self._cached_list

    def find_existing_xml_in_list(self, network_code: str, station_code: str, file_list: List[dict]) -> Optional[str]:
        """
        Searches for a specific station within a pre-downloaded file list.
        Looks for patterns in the format 'NETWORK_STATION' (e.g., 'IV_ROME').

        Args:
            network_code (str): FDSN network code.
            station_code (str): FDSN station code.
            file_list (List[dict]): List of files to search in.

        Returns:
            Optional[str]: The file ID if found, otherwise None.
        """
        search_pattern = f"{network_code}_{station_code}".upper()
        for item in file_list:
            if isinstance(item, dict):
                filename = (item.get("name") or "").upper()
                if search_pattern in filename:
                    # Return the ID preferably, or the name as a fallback
                    return str(item.get("id") or item.get("name"))
        return None
    
    def find_existing_xml(self, network_code: str, station_code: str) -> Optional[str]:
        """
        Queries the cache to check if a station is already present on Yasmine.
        Useful for checking before overwriting.
        """
        lista_file = self.get_all_files()
        return self.find_existing_xml_in_list(network_code, station_code, lista_file)
        
    def get_all_imported_xmls(self) -> List[dict]:
        """
        Executes a LIVE call (without cache) to get the current state
        of the Yasmine archive. Includes robust logic to parse 
        both dictionary and list responses.

        Returns:
            List[dict]: Updated list of XML files.
        """
        try:
            response = requests.get(self.api_url, timeout=10)
            if response.status_code == 200:
                res_json = response.json()
                # Depending on the Yasmine API version, the response
                # might be wrapped in a 'data' key or be a pure list.
                if isinstance(res_json, dict) and 'data' in res_json:
                    return res_json['data']
                elif isinstance(res_json, list):
                    return res_json
            return []
        except Exception as e:
            log_network_error(logger, "Yasmine", e, detail="get_all_imported_xmls")
            return []

    def delete_xml(self, item_id) -> bool:
        """
        Deletes an XML file from the Yasmine server via a DELETE request.

        Args:
            item_id (int or str): The unique ID or name of the file to remove.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        base_url = self.api_url.rstrip('/')
        url = f"{base_url}/{item_id}"
        try:
            # Yasmine's API often requires the ID both in the URL and the body
            response = requests.delete(url, json={"id": int(item_id)}, timeout=10)
            return response.status_code in [200, 204]
        except Exception as e:
            log_network_error(logger, "Yasmine", e, detail=f"delete_xml id={item_id}")
            return False

    def upload_xml(self, xml_bytes: bytes, station_code: str) -> Optional[int]:
        """
        Sends a StationXML file to the Yasmine server via a multipart/form-data request.
        Immediately after the upload, queries the server to extract the newly generated ID.

        Args:
            xml_bytes (bytes): Raw content of the XML file.
            station_code (str): Used to assign the name to the uploaded file.

        Returns:
            Optional[int]: The new file ID on Yasmine, or None in case of error.
        """
        base_url = self.api_url.rstrip('/')
        url = f"{base_url}/ie/"
        
        # Prepare multipart payload to simulate an HTML form upload
        files = {'xml-path': (f"{station_code}.xml", xml_bytes, 'text/xml')}
        data = {'name': station_code}
        
        try:
            response = requests.post(url, files=files, data=data, timeout=30)
            if response.status_code in [200, 201]:
                logger.info(f"Upload of {station_code} completed. Retrieving ID...")
                
                # Live call to find the newly generated ID from Yasmine's database
                updated_list = self.get_all_imported_xmls()
                if updated_list:
                    for item in updated_list:
                        if isinstance(item, dict) and item.get('name') == station_code:
                            new_id = item.get('id')
                            logger.info(f"ID {new_id} successfully retrieved for {station_code}.")
                            return new_id
                            
                logger.error(f"File uploaded, but not found in Yasmine's list for {station_code}.")
                return None
            else:
                logger.error(f"Yasmine upload error: {response.status_code}")
                return None
        except Exception as e:
            log_network_error(logger, "Yasmine", e, detail=f"upload_xml station={station_code}")
            return None