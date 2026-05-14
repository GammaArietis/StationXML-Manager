"""Reti sismiche: accesso dati e persistenza (senza AppState)."""

from __future__ import annotations

from typing import List, Optional

from core.models.base_models import Network
from database.daos.network_dao import NetworkDAO


class NetworkService:
    def __init__(self, dao: NetworkDAO) -> None:
        self._dao = dao

    def list_networks(self) -> List[Network]:
        return self._dao.get_all()

    def get_network_by_id(self, network_id: int) -> Optional[Network]:
        return self._dao.get_by_id(network_id)

    def insert_network(self, network: Network) -> Network:
        return self._dao.insert(network)

    def update_network(self, network: Network) -> bool:
        return self._dao.update(network)

    def delete_network(self, network_id: int) -> bool:
        return self._dao.delete(network_id)
