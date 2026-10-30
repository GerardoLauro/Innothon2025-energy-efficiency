"""Classificazione delle offerte e scelta dell'obiettivo energetico."""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Optional


class OfferType(str, Enum):
    """Tipologie di offerta energetica supportate."""

    ENEL_FIX_BUSINESS = "enel_fix_business"
    ENEL_FLEX_BUSINESS_PUN_TRI = "enel_flex_business_pun_tri"
    PLACET_FISSA = "placet_fissa"
    PLACET_VARIABILE = "placet_variabile"


_FIX_KEYWORDS = {
    "fix",
    "fissa",
    "monoraria",
    "prezzo bloccato",
    "prezzo fisso",
}

_FLEX_KEYWORDS = {
    "flex",
    "variabile",
    "indicizzata",
    "multi-oraria",
}

_PUN_MARKERS = {
    "pun",
    "f1",
    "f2",
    "f3",
    "tri-oraria",
    "fasce",
}

_PLACET = "placet"


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("ASCII")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _contains_any(text: str, keywords: set[str]) -> bool:
    tokens = set(text.split())
    for keyword in keywords:
        if keyword in tokens or keyword in text:
            return True
    return False


def classify_offer(text: str) -> Optional[OfferType]:
    """Classifica una descrizione di offerta in un tipo normalizzato."""
    normalized = _normalize(text)
    if not normalized:
        return None

    if _PLACET in normalized:
        if _contains_any(normalized, _FLEX_KEYWORDS.union(_PUN_MARKERS)):
            return OfferType.PLACET_VARIABILE
        return OfferType.PLACET_FISSA

    if _contains_any(normalized, _FLEX_KEYWORDS.union(_PUN_MARKERS)):
        return OfferType.ENEL_FLEX_BUSINESS_PUN_TRI

    if _contains_any(normalized, _FIX_KEYWORDS):
        return OfferType.ENEL_FIX_BUSINESS

    return None


def infer_objective(offer: OfferType | None) -> str:
    """Determina l'obiettivo primario in base al tipo di offerta."""
    if offer in {OfferType.ENEL_FIX_BUSINESS, OfferType.PLACET_FISSA}:
        return "min_peak"
    if offer in {OfferType.ENEL_FLEX_BUSINESS_PUN_TRI, OfferType.PLACET_VARIABILE}:
        return "min_cost"
    return "min_cost"


def build_peak_constraint_hint(contractual_power: float | None, offer: OfferType | None) -> Optional[str]:
    """Suggerisce un vincolo di picco quando la potenza contrattuale e nota."""
    if contractual_power is None:
        return None
    if offer in {OfferType.ENEL_FIX_BUSINESS, OfferType.PLACET_FISSA}:
        return (
            "Potenza contrattuale dichiarata: aggiungere un vincolo di picco massimo "
            f"<= {contractual_power:g} kW per ridurre penali."
        )
    if offer in {OfferType.ENEL_FLEX_BUSINESS_PUN_TRI, OfferType.PLACET_VARIABILE}:
        return (
            "Potenza contrattuale disponibile: valutare un vincolo di picco ausiliario "
            f"<= {contractual_power:g} kW accanto all'obiettivo min_cost."
        )
    return None


__all__ = ["OfferType", "classify_offer", "infer_objective", "build_peak_constraint_hint"]
