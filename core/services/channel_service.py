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

    def save_channel_with_triad_sync(self, channel: Channel) -> tuple[Optional[Channel], List[str]]:
        """
        Save one channel and, when an existing epoch end_date changes, propagate it
        to sibling channels in the same triaxial prefix and start epoch.
        """
        old_channel = self._cha.get_by_id(channel.id) if channel.id is not None else None
        saved_cha = self.save_channel(channel)
        if not saved_cha:
            return None, []

        synced_codes: List[str] = []
        new_end = (saved_cha.end_date or "").strip()
        old_end = (old_channel.end_date or "").strip() if old_channel else ""
        if not old_channel or not new_end or new_end == old_end:
            return saved_cha, synced_codes

        code = (saved_cha.code or "").strip().upper()
        if len(code) < 2:
            return saved_cha, synced_codes

        prefix = code[:2]
        start_date = saved_cha.start_date
        for sibling in self._cha.get_by_station_id(saved_cha.station_id):
            if sibling.id == saved_cha.id:
                continue
            sibling_code = (sibling.code or "").strip().upper()
            if not sibling_code.startswith(prefix):
                continue
            if sibling.start_date != start_date:
                continue
            sibling.end_date = new_end
            if self._cha.update(sibling):
                synced_codes.append(sibling.code)

        if synced_codes:
            self._sta.update_sync_hash(saved_cha.station_id, "MODIFIED_BY_CHANNEL")
            logger.info(
                "Triad end_date synced from %s to siblings: %s",
                saved_cha.code,
                ", ".join(synced_codes),
            )

        return saved_cha, synced_codes

    def delete_channel(self, channel_id: int) -> bool:
        return self._cha.delete(channel_id)
