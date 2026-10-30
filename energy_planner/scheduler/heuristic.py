"""Placeholder per heuristiche di scheduling."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def build_feasible_baseline(instance: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Tenta di costruire uno schedule triviale a partire dall'istanza.

    Restituisce uno schedule vuoto quando l'istanza non contiene attivita o
    un messaggio che indica la mancanza di una heuristica.
    """

    activities = instance.get("activities", [])
    if not activities:
        return {"schedule": []}, None

    return None, "Greedy baseline non implementata per istanze non banali."


__all__ = ["build_feasible_baseline"]
