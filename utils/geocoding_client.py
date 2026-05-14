import logging
import requests

logger = logging.getLogger(__name__)

def fetch_geography_from_coords(lat, lon):
    """
    Queries OpenStreetMap (Nominatim) with improved extraction logic
    for remote sites and seismic stations.
    """
    if lat == 0.0 and lon == 0.0:
        return None

    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=it,en"
    
    headers = {
        "User-Agent": "StationXML_Manager_App/1.1 (research_metadata_tool)"
    }

    try:
        logger.info(f"Advanced geographic search for Lat: {lat}, Lon: {lon}")
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            if "address" in data:
                addr = data["address"]
                
                # 1. Standard administrative data extraction
                town = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or ""
                county = addr.get("county") or addr.get("province") or ""
                region = addr.get("state") or addr.get("region") or ""
                country = addr.get("country") or ""

                # 2. IMPROVED DESCRIPTION LOGIC (Site/Locality)
                # Create a preference hierarchy for rural/mountain areas
                candidates = [
                    addr.get("amenity"),    # Names of buildings or specific points
                    addr.get("natural"),    # Natural elements (e.g., Mount Etna)
                    addr.get("peak"),       # Mountain peaks
                    addr.get("tourism"),    # Scenic points
                    addr.get("historic"),   # Historic sites
                    addr.get("hamlet"),     # Very small settlements
                    addr.get("road"),       # Road (if present)
                    addr.get("suburb"),     # Neighborhood
                ]

                # Takes the first non-null value in the candidate list
                desc = next((c for c in candidates if c), "")

                # 3. SMART FALLBACK: If desc is still empty, use display_name
                # Nominatim's display_name is a long string (e.g., "Monte Cairo, Terelle, FR, Lazio, Italia")
                if not desc and "display_name" in data:
                    parts = data["display_name"].split(",")
                    if len(parts) > 0:
                        # Take the first part (usually the most specific)
                        desc = parts[0].strip()
                
                # If absolutely nothing else, use the town/city name
                if not desc:
                    desc = town

                return {
                    "town": str(town).strip(),
                    "county": str(county).strip().replace("Province of ", "").replace("Provincia di ", ""),
                    "region": str(region).strip(),
                    "country": str(country).strip(),
                    "description": str(desc).strip()
                }
            else:
                return "DATA_NOT_FOUND"
        else:
            logger.error(f"OSM API error: {response.status_code}")
            return "API_ERROR"
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during geographic request: {e}")
        return "NETWORK_ERROR"