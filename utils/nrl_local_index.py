"""Enumerazione percorsi foglia NRL e merge nell'indice matematico locale (NiceGUI / batch)."""

from __future__ import annotations

from typing import Any, Dict, List

from utils.equipment_math_hash import get_datalogger_hash, get_sensor_hash
from utils.nrl_client import NRLManager


def collect_sensor_leaf_paths(manager: NRLManager) -> List[List[str]]:
    paths: List[List[str]] = []
    queue: List[List[str]] = [[]]
    while queue:
        curr = queue.pop(0)
        try:
            opts = manager.get_sensor_options(*curr)
            if opts is None:
                paths.append(curr)
            else:
                for o in opts:
                    queue.append(curr + [o])
        except Exception:
            pass
    return paths


def collect_datalogger_leaf_paths(manager: NRLManager) -> List[List[str]]:
    paths: List[List[str]] = []
    queue: List[List[str]] = [[]]
    while queue:
        curr = queue.pop(0)
        try:
            opts = manager.get_datalogger_options(*curr)
            if opts is None:
                paths.append(curr)
            else:
                for o in opts:
                    queue.append(curr + [o])
        except Exception:
            pass
    return paths


def merge_sensor_path_into_cache(manager: NRLManager, path: List[str], cache: Dict[str, Any]) -> None:
    path_str = " -> ".join(path)
    try:
        model = manager.fetch_sensor(path)
        if model:
            h = get_sensor_hash(model)
            if h not in cache["sensors"]:
                cache["sensors"][h] = []
            if path_str not in cache["sensors"][h]:
                cache["sensors"][h].append(path_str)
    except Exception:
        pass


def merge_datalogger_path_into_cache(manager: NRLManager, path: List[str], cache: Dict[str, Any]) -> None:
    path_str = " -> ".join(path)
    try:
        model = manager.fetch_datalogger(path)
        if model:
            h = get_datalogger_hash(model)
            if h not in cache["dataloggers"]:
                cache["dataloggers"][h] = []
            if path_str not in cache["dataloggers"][h]:
                cache["dataloggers"][h].append(path_str)
    except Exception:
        pass
