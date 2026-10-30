"""Generazione del report sulle assunzioni applicate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(slots=True)
class Assumption:
    """Rappresenta un elemento di assunzione da riportare."""

    category: str
    description: str


def build_assumption_report(assumptions: Iterable[Assumption]) -> str:
    """Produce un testo leggibile contenente l'elenco delle assunzioni applicate."""
    grouped: dict[str, List[str]] = {}
    for item in assumptions:
        grouped.setdefault(item.category, []).append(item.description)

    lines: List[str] = []
    if not grouped:
        return "Nessuna assunzione applicata nella sessione corrente."

    lines.append("Assunzioni applicate")
    lines.append("====================")
    for category in sorted(grouped):
        lines.append(f"\n{category}")
        for desc in grouped[category]:
            lines.append(f"- {desc}")
    return "\n".join(lines)


def default_assumptions_from_context(
    *,
    used_flat_prices: bool = False,
    used_default_workforce: bool = False,
    vague_ranges: Iterable[str] | None = None,
    machines_with_unknown_power: Iterable[str] | None = None,
) -> List[Assumption]:
    """Costruisce una lista di assunzioni standard da contesto normalizzato."""
    entries: List[Assumption] = []
    if used_flat_prices:
        entries.append(Assumption("Prezzi", "Serie flat 0.25 EUR/kWh utilizzata come fallback."))
    if used_default_workforce:
        entries.append(Assumption("Workforce", "Disponibilita predefinita 1 persona/slot applicata."))
    if vague_ranges:
        for expression in vague_ranges:
            entries.append(Assumption("Finestre temporali", f"Espressione vaga interpretata: {expression}."))
    if machines_with_unknown_power:
        for machine in machines_with_unknown_power:
            entries.append(Assumption("Macchine", f"Potenza non dichiarata per {machine}: impostata a 0 kW."))
    return entries


__all__ = ["Assumption", "build_assumption_report", "default_assumptions_from_context"]
