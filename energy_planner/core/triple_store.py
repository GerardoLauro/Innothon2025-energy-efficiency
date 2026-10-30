"""Archivio in-memory delle triplette estratte dal flusso."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional, Sequence

_ALLOWED_PREFIXES = (
    "objective",
    "horizon",
    "time",
    "price",
    "workforce",
    "machine:",
    "activity:",
    "lock",
    "note",
)


def _make_hashable(value: object) -> object:
    if isinstance(value, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_make_hashable(item) for item in value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    return repr(value)


@dataclass(slots=True)
class Triple:
    """Tripletta soggetto-relazione-valore con metadati opzionali."""

    subject: str
    relation: str
    value: object
    meta: Optional[dict[str, object]] = None

    def key(self) -> tuple[str, str, object]:
        """Chiave di deduplicazione basata su soggetto, relazione e valore."""
        return self.subject, self.relation, _make_hashable(self.value)


@dataclass(slots=True)
class TripleStore:
    """Memorizza le triplette con ordine stabile e query filtrate."""

    _triples: List[Triple] = field(default_factory=list)
    _seen: set[tuple[str, str, object]] = field(default_factory=set)

    def ingest(self, triples: Sequence[Triple]) -> None:
        """Inserisce triplette deduplicando quelle gia presenti."""
        for triple in triples:
            _validate_subject(triple.subject)
            key = triple.key()
            if key in self._seen:
                continue
            self._triples.append(triple)
            self._seen.add(key)

    def query(
        self,
        *,
        subject_prefix: Optional[str] = None,
        relation: Optional[str] = None,
    ) -> Iterator[Triple]:
        """Restituisce un iteratore sulle triplette che soddisfano i filtri."""
        for triple in self._triples:
            if subject_prefix and not triple.subject.startswith(subject_prefix):
                continue
            if relation and triple.relation != relation:
                continue
            yield triple

    def to_dict(self) -> list[dict[str, object]]:
        """Produce un dump leggibile (utile per audit e report)."""
        output: list[dict[str, object]] = []
        for triple in self._triples:
            entry = {
                "subject": triple.subject,
                "relation": triple.relation,
                "value": triple.value,
            }
            if triple.meta:
                entry["meta"] = dict(triple.meta)
            output.append(entry)
        return output


def _validate_subject(subject: str) -> None:
    """Verifica che il soggetto rispetti i prefissi ammessi."""
    if not any(subject.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        raise ValueError(f"Soggetto non riconosciuto: {subject}")


__all__ = ["Triple", "TripleStore"]
