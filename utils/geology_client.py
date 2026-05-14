import logging
import requests

logger = logging.getLogger(__name__)

def fetch_geology_from_coords(lat, lon):
    """
    Queries the Macrostrat v2 API to obtain the site's geology.
    Returns a formatted string aligned with FDSN best-practices.
    """
    if lat == 0.0 and lon == 0.0:
        return ""

    # Official and stable V2 endpoint for point queries
    url = f"https://macrostrat.org/api/v2/geologic_units/map?lat={lat}&lng={lon}"
    
    try:
        logger.info(f"Geology search for Lat: {lat}, Lon: {lon}")
        # 5 seconds timeout to avoid blocking the interface
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            # The official V2 structure is data["success"]["data"]
            if "success" in data and "data" in data["success"] and len(data["success"]["data"]) > 0:
                # Take the first rock unit returned (the surface one)
                unit = data["success"]["data"][0]
                
                # Extract lithology and formation name
                lithology = str(unit.get("lith", "")).strip().upper()
                rock_type = str(unit.get("name", "")).strip()
                
                # Basic cleanup if data is missing
                if not lithology and rock_type:
                    lithology = rock_type.upper()
                elif not lithology:
                    lithology = "ROCK"
                    
                # FDSN Formatting (e.g., "LIMESTONE (Maiolica)")
                geology_str = lithology
                if rock_type and rock_type.upper() != lithology and rock_type.upper() != "NULL":
                    # Avoid inserting very long formation names
                    if len(rock_type) < 40:
                        geology_str += f" ({rock_type})"
                
                return geology_str
            else:
                return "DATA_NOT_FOUND"
        else:
            logger.error(f"Macrostrat API error (Status {response.status_code}): The endpoint might be incorrect.")
            return "API_ERROR"
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during geological request: {e}")
        return "NETWORK_ERROR"