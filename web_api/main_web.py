from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

from core.config import (
    api_rate_limit_enabled,
    api_rate_limit_per_minute,
    cors_allow_credentials,
    cors_allow_origins,
    get_settings,
)
from core.models.base_models import Network, Station, Channel, Sensor, Datalogger, Preamplifier, Operator
from core.services.catalog_service import CatalogService, EquipmentInUseError
from core.services.channel_service import ChannelService
from core.services.equipment_service import EquipmentService
from core.services.network_service import NetworkService
from core.services.station_service import StationService
from core.validators.geo_validators import ValidationError
from core.database import init_database
from database.daos.network_dao import NetworkDAO
from database.daos.station_dao import StationDAO
from database.daos.channel_dao import ChannelDAO
from database.daos.equipment_dao import EquipmentDAO
from utils.logging_config import configure_application_logging
from web_api.rate_limit_middleware import RateLimitMiddleware

app = FastAPI(
    title="StationXML Manager API",
    description="API REST professionale per la gestione di metadati sismici FDSN",
    version="1.1.0",
)

_settings = get_settings()
_cors_origins = cors_allow_origins(_settings)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=cors_allow_credentials(_cors_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)
app.add_middleware(
    RateLimitMiddleware,
    calls_per_minute=api_rate_limit_per_minute(_settings),
    enabled=api_rate_limit_enabled(_settings),
    path_prefix="/api/",
)

db_manager = init_database(settings=_settings)

net_dao = NetworkDAO(db_manager)
sta_dao = StationDAO(db_manager)
cha_dao = ChannelDAO(db_manager)
equ_dao = EquipmentDAO(db_manager)

configure_application_logging()

# Servizi condivisi (REST = stesso flusso logico di CatalogService / StationService / …)
net_svc = NetworkService(net_dao)
sta_svc = StationService(sta_dao)
cha_svc = ChannelService(cha_dao, sta_dao)
catalog_svc = CatalogService(equ_dao)
equ_svc: EquipmentService = catalog_svc.equipment


# ==========================================
# NETWORKS
# ==========================================
@app.get("/api/networks", response_model=List[Network], tags=["Networks"])
def get_networks():
    return net_svc.list_networks()


@app.get("/api/networks/{network_id}", response_model=Network, tags=["Networks"])
def get_network(network_id: int):
    network = net_svc.get_network_by_id(network_id)
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    return network


@app.post("/api/networks", response_model=Network, tags=["Networks"])
def save_network(network: Network):
    try:
        if network.id is None:
            return net_svc.insert_network(network)
        success = net_svc.update_network(network)
        if not success:
            raise HTTPException(status_code=404, detail="Network not found for update")
        return network
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/networks/{network_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Networks"])
def delete_network(network_id: int):
    if not net_svc.delete_network(network_id):
        raise HTTPException(status_code=404, detail="Network not found")


# ==========================================
# STATIONS
# ==========================================
@app.get("/api/stations", response_model=List[Station], tags=["Stations"])
def get_all_stations(network_id: Optional[int] = Query(None, description="Filter stations by network ID")):
    if network_id:
        return sta_svc.get_stations_by_network(network_id)
    return sta_svc.get_all_stations()


@app.get("/api/stations/{station_id}", response_model=Station, tags=["Stations"])
def get_station(station_id: int):
    station = sta_svc.get_station_by_id(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    return station


@app.post("/api/stations", response_model=Station, tags=["Stations"])
def save_station(station: Station):
    try:
        saved = sta_svc.save_station(station)
        if station.id is not None and saved is None:
            raise HTTPException(status_code=404, detail="Station not found for update")
        if saved is None:
            raise HTTPException(status_code=400, detail="Failed to save station")
        return saved
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/stations/{station_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Stations"])
def delete_station(station_id: int):
    if not sta_svc.delete_station(station_id):
        raise HTTPException(status_code=404, detail="Station not found")


# ==========================================
# CHANNELS
# ==========================================
@app.get("/api/stations/{station_id}/channels", response_model=List[Channel], tags=["Channels"])
def get_channels_by_station(station_id: int):
    return cha_svc.get_channels_by_station(station_id)


@app.get("/api/channels/{channel_id}", response_model=Channel, tags=["Channels"])
def get_channel(channel_id: int):
    channel = cha_svc.get_channel_by_id(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@app.post("/api/channels", response_model=Channel, tags=["Channels"])
def save_channel(channel: Channel):
    try:
        saved = cha_svc.save_channel(channel)
        if channel.id is not None and saved is None:
            raise HTTPException(status_code=404, detail="Channel not found for update")
        if saved is None:
            raise HTTPException(status_code=400, detail="Failed to save channel")
        return saved
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Channels"])
def delete_channel(channel_id: int):
    if not cha_svc.delete_channel(channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")


# ==========================================
# CATALOGS (Equipment & Operators)
# ==========================================

@app.get("/api/equipment/sensors/{sensor_id}", response_model=Sensor, tags=["Equipment"])
def get_equipment_sensor(sensor_id: int):
    sensor = equ_svc.get_sensor(sensor_id)
    if sensor is None:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return sensor


@app.get("/api/catalog/sensors", response_model=List[Sensor], tags=["Catalog"])
def get_sensor_catalog():
    return equ_svc.list_sensors()


@app.post("/api/catalog/sensors", response_model=Sensor, tags=["Catalog"])
def save_sensor(sensor: Sensor):
    try:
        saved = catalog_svc.save_sensor(sensor)
        if not saved:
            raise HTTPException(status_code=400, detail="Failed to save sensor")
        return saved
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/catalog/sensors/{sensor_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Catalog"])
def delete_sensor(sensor_id: int):
    try:
        if not catalog_svc.delete_sensor(sensor_id):
            raise HTTPException(status_code=404, detail="Sensor not found")
    except EquipmentInUseError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/equipment/dataloggers/{datalogger_id}", response_model=Datalogger, tags=["Equipment"])
def get_equipment_datalogger(datalogger_id: int):
    datalogger = equ_svc.get_datalogger(datalogger_id)
    if datalogger is None:
        raise HTTPException(status_code=404, detail="Datalogger not found")
    return datalogger


@app.get("/api/catalog/dataloggers", response_model=List[Datalogger], tags=["Catalog"])
def get_datalogger_catalog():
    return equ_svc.list_dataloggers()


@app.post("/api/catalog/dataloggers", response_model=Datalogger, tags=["Catalog"])
def save_datalogger(datalogger: Datalogger):
    try:
        saved = catalog_svc.save_datalogger(datalogger)
        if not saved:
            raise HTTPException(status_code=400, detail="Failed to save datalogger")
        return saved
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/catalog/dataloggers/{datalogger_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Catalog"])
def delete_datalogger(datalogger_id: int):
    try:
        if not catalog_svc.delete_datalogger(datalogger_id):
            raise HTTPException(status_code=404, detail="Datalogger not found")
    except EquipmentInUseError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/catalog/preamplifiers", response_model=List[Preamplifier], tags=["Catalog"])
def get_preamplifier_catalog():
    return catalog_svc.list_preamplifiers()


@app.post("/api/catalog/preamplifiers", response_model=Preamplifier, tags=["Catalog"])
def save_preamplifier(preamp: Preamplifier):
    try:
        saved = catalog_svc.save_preamplifier(preamp)
        if not saved:
            raise HTTPException(status_code=400, detail="Failed to save preamplifier")
        return saved
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/catalog/preamplifiers/{preamp_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Catalog"])
def delete_preamplifier(preamp_id: int):
    try:
        if not catalog_svc.delete_preamplifier(preamp_id):
            raise HTTPException(status_code=404, detail="Preamplifier not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/catalog/operators", response_model=List[Operator], tags=["Catalog"])
def get_operator_catalog():
    return catalog_svc.list_operators()


@app.post("/api/catalog/operators", response_model=Operator, tags=["Catalog"])
def save_operator(operator: Operator):
    try:
        saved = catalog_svc.save_operator(operator)
        if not saved:
            raise HTTPException(status_code=400, detail="Failed to save operator")
        return saved
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/catalog/operators/{operator_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Catalog"])
def delete_operator(operator_id: int):
    try:
        if not catalog_svc.delete_operator(operator_id):
            raise HTTPException(status_code=404, detail="Operator not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
