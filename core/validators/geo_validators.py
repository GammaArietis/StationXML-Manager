import logging

logger = logging.getLogger(__name__)

class ValidationError(Exception):
    """Custom exception for seismological data validation errors."""
    pass

def validate_coordinates(latitude: float, longitude: float, elevation: float) -> bool:
    """
    Verifies that coordinates respect standard WGS84 geographical limits.
    """
    if not (-90.0 <= latitude <= 90.0):
        raise ValidationError(f"Invalid latitude: {latitude}. Must be between -90 and 90.")
    
    if not (-180.0 <= longitude <= 180.0):
        raise ValidationError(f"Invalid longitude: {longitude}. Must be between -180 and 180.")
    
    # Elevation in FDSN StationXML is in meters. A reasonable lower limit 
    # might be the Mariana Trench (-11000m) or Everest (8848m).
    if not (-15000.0 <= elevation <= 10000.0):
        logger.warning(f"Anomalous elevation detected: {elevation} meters.")
        
    return True

def validate_channel_code(code: str) -> bool:
    """
    Verifies that the channel code respects the SEED/FDSN standard (e.g., 'HHZ').
    Usually exactly 3 alphanumeric characters.
    """
    if len(code) != 3 or not code.isalnum():
        raise ValidationError(f"Invalid channel code: '{code}'. Must be exactly 3 characters.")
    return True

def validate_sample_rate(sample_rate: float) -> bool:
    """The sample rate cannot be negative or zero."""
    if sample_rate <= 0:
        raise ValidationError(f"Invalid sample rate: {sample_rate} Hz. Must be > 0.")
    return True