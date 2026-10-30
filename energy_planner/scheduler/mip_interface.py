"""Interfaccia placeholder per il solver MIP."""

from __future__ import annotations

from typing import Any, Dict


def solve_mip(instance: Dict[str, Any], *, solver: str = "auto") -> Dict[str, Any]:
    """Stub per la risoluzione MIP: da sostituire con integrazione reale."""
    raise NotImplementedError(
        "solve_mip non implementato: integrare un solver (pulp/ortools o commerciale) "
        "definendo variabili e vincoli secondo lo schema dell'istanza."
    )


__all__ = ["solve_mip"]
