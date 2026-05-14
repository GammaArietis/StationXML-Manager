import logging
from typing import List, Optional

from core.models.base_models import Network
from core.services.network_service import NetworkService
from database.daos.network_dao import NetworkDAO
from core.state import AppState

logger = logging.getLogger(__name__)


class NetworkController:
    """
    Gestisce reti sismiche e stato UI; la persistenza passa da NetworkService.
    """

    def __init__(self, dao: NetworkDAO, app_state: AppState) -> None:
        self.dao = dao
        self.state = app_state
        self._service = NetworkService(dao)

    @property
    def network_service(self) -> NetworkService:
        return self._service

    def get_all_networks(self) -> List[Network]:
        return self._service.list_networks()

    def select_network(self, network_id: int) -> bool:
        if not self.state.can_navigate_away():
            logger.warning("Network change attempt blocked: unsaved modifications exist.")
            return False
        self.state.current_network = network_id
        logger.info("Active network set to ID: %s", network_id)
        return True

    def save_network(self, network: Network) -> Optional[Network]:
        try:
            if network.id is None:
                saved_network = self._service.insert_network(network)
            else:
                success = self._service.update_network(network)
                saved_network = network if success else None
            if saved_network:
                self.state.mark_clean()
                logger.info("Network %s successfully saved.", saved_network.code)
                return saved_network
            return None
        except Exception as e:
            logger.error("Critical error while saving network: %s", e)
            raise

    def delete_network(self, network_id: int) -> bool:
        success = self._service.delete_network(network_id)
        if success and self.state.current_network == network_id:
            self.state.current_network = None
            self.state.mark_clean()
        return success

    def get_network_by_id(self, network_id: int) -> Optional[Network]:
        return self._service.get_network_by_id(network_id)
