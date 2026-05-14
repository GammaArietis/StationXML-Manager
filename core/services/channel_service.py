"""Canali (streams): validazione e invalidazione sync stazione (senza AppState)."""

from __future__ import annotations

import logging
from typing import List, Optional

from core.models.base_models import Channel
from database.daos.channel_dao import ChannelDAO
from database.daos.station_dao import StationDAO

logger = logging.getLogger(__name__)


class ChannelService:
    def __init__(self, channel_dao: ChannelDAO, station_dao: StationDAO) -> None:
        self._cha = channel_dao
        self._sta = station_dao

    def get_channel_by_id(self, channel_id: int) -> Optional[Channel]:
        return self._cha.get_by_id(channel_id)

    def get_channels_by_station(self, station_id: int) -> List[Channel]:
        return self._cha.get_by_station_id(station_id)

    def save_channel(self, channel: Channel) -> Optional[Channel]:
        if not (0 <= channel.azimuth <= 360):
            raise ValueError("Azimuth must be between 0 and 360 degrees.")
        if channel.id is None:
            saved_cha = self._cha.insert(channel)
        else:
            success = self._cha.update(channel)
            saved_cha = channel if success else None
        if saved_cha:
            self._sta.update_sync_hash(channel.station_id, "MODIFIED_BY_CHANNEL")
            logger.info(
                "Channel %s saved. Station %s sync invalidated.",
                saved_cha.code,
                channel.station_id,
            )
        return saved_cha

    def delete_channel(self, channel_id: int) -> bool:
        return self._cha.delete(channel_id)
