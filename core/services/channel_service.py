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
        Save one channel and, when end_date is set, propagate it to sibling
        channels in the same triaxial prefix and start epoch.
        """
        synced_codes: List[str] = []
        self._validate_channel(channel)
        with self._cha.db.write_transaction() as conn:
            saved_cha = self._save_channel_in_transaction(conn, channel)
            if not saved_cha:
                raise RuntimeError("Channel save failed inside triad transaction.")

            self._invalidate_station_sync_in_transaction(conn, saved_cha.station_id)
            new_end = (saved_cha.end_date or "").strip()
            if not new_end:
                return saved_cha, synced_codes

            code = (saved_cha.code or "").strip().upper()
            if len(code) < 2:
                return saved_cha, synced_codes

            prefix = code[:2]
            start_date = self._normalize_epoch_for_compare(saved_cha.start_date)
            logger.info(
                "[BACKEND SYNC] Canale corrente: %s, End Date da applicare: %s",
                saved_cha.code,
                saved_cha.end_date,
            )

            cursor = conn.execute(
                "SELECT * FROM channel WHERE station_id = ? ORDER BY code, location_code",
                (saved_cha.station_id,),
            )
            for row in cursor.fetchall():
                sibling = self._cha._row_to_model(row)
                if not sibling or sibling.id == saved_cha.id:
                    continue
                sibling_code = (sibling.code or "").strip().upper()
                if not sibling_code.startswith(prefix):
                    continue
                if self._normalize_epoch_for_compare(sibling.start_date) != start_date:
                    continue
                logger.info(
                    "[BACKEND SYNC] Trovato canale fratello da aggiornare: %s",
                    sibling.code,
                )
                result = conn.execute(
                    "UPDATE channel SET end_date = ? WHERE id = ?",
                    (new_end, sibling.id),
                )
                if result.rowcount != 1:
                    raise RuntimeError(
                        f"Triad sync failed while updating sibling channel {sibling.code}."
                    )
                synced_codes.append(sibling.code)

            if synced_codes:
                logger.info(
                    "Triad end_date synced from %s to siblings: %s",
                    saved_cha.code,
                    ", ".join(synced_codes),
                )

            return saved_cha, synced_codes

    @staticmethod
    def _validate_channel(channel: Channel) -> None:
        if not (0 <= channel.azimuth <= 360):
            raise ValueError("Azimuth must be between 0 and 360 degrees.")

    def _save_channel_in_transaction(self, conn, channel: Channel) -> Optional[Channel]:
        if channel.id is None:
            cursor = conn.execute(
                """
                INSERT INTO channel (
                    station_id, code, location_code, latitude, longitude, elevation,
                    depth, sample_rate, azimuth, dip, sensor_id,
                    datalogger_id, start_date, end_date, overall_sensitivity,
                    sensor_serial_number, datalogger_serial_number, types,
                    restricted_status, clock_drift, calibration_units, pre_amplifier_id,
                    pre_amplifier_serial_number, pre_amplifier_gain, comments
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel.station_id, channel.code, channel.location_code,
                    channel.latitude, channel.longitude, channel.elevation,
                    channel.depth, channel.sample_rate, channel.azimuth,
                    channel.dip, channel.sensor_id, channel.datalogger_id,
                    channel.start_date, channel.end_date, channel.overall_sensitivity,
                    channel.sensor_serial_number, channel.datalogger_serial_number,
                    channel.types, getattr(channel, "restricted_status", None) or "open",
                    channel.clock_drift, channel.calibration_units,
                    channel.pre_amplifier_id, channel.pre_amplifier_serial_number,
                    channel.pre_amplifier_gain, channel.comments,
                ),
            )
            channel.id = cursor.lastrowid
            return channel

        result = conn.execute(
            """
            UPDATE channel SET
                code=?, location_code=?, latitude=?, longitude=?, elevation=?,
                depth=?, sample_rate=?, azimuth=?, dip=?, sensor_id=?,
                datalogger_id=?, start_date=?, end_date=?, overall_sensitivity=?,
                sensor_serial_number=?, datalogger_serial_number=?, types=?,
                restricted_status=?, clock_drift=?, calibration_units=?, pre_amplifier_id=?,
                pre_amplifier_serial_number=?, pre_amplifier_gain=?, comments=?
            WHERE id=?
            """,
            (
                channel.code, channel.location_code, channel.latitude,
                channel.longitude, channel.elevation, channel.depth,
                channel.sample_rate, channel.azimuth, channel.dip,
                channel.sensor_id, channel.datalogger_id,
                channel.start_date, channel.end_date, channel.overall_sensitivity,
                channel.sensor_serial_number, channel.datalogger_serial_number,
                channel.types, getattr(channel, "restricted_status", None) or "open",
                channel.clock_drift, channel.calibration_units,
                channel.pre_amplifier_id, channel.pre_amplifier_serial_number,
                channel.pre_amplifier_gain, channel.comments, channel.id,
            ),
        )
        return channel if result.rowcount == 1 else None

    @staticmethod
    def _invalidate_station_sync_in_transaction(conn, station_id: int) -> None:
        conn.execute(
            "UPDATE yasmine_sync_state SET local_xml_hash = ? WHERE station_id = ?",
            ("MODIFIED_BY_CHANNEL", station_id),
        )

    @staticmethod
    def _normalize_epoch_for_compare(value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip().replace("T", " ")
        if not text:
            return ""
        if len(text) == 10:
            return f"{text} 00:00:00"
        if len(text) == 16:
            return f"{text}:00"
        return text[:19] if len(text) >= 19 else text

    def delete_channel(self, channel_id: int) -> bool:
        return self._cha.delete(channel_id)
