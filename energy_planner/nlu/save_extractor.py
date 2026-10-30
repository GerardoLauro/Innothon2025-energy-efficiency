"""Estrazione robusta dei blocchi >>> SAVE da output LLM."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterator, List, Mapping, Sequence

from energy_planner.core.triple_store import Triple

logger = logging.getLogger(__name__)

_SAVE_PATTERN = re.compile(r">>>\s*(SAVE|CHECKLIST)", re.IGNORECASE)


@dataclass(slots=True)
class SaveBlock:
    """Contiene i dati estratti da un blocco >>> SAVE."""

    triples: List[Triple]
    raw_json: str
    start: int
    end: int


@dataclass(slots=True)
class SaveBlockError:
    """Errore di estrazione relativo a un blocco >>> SAVE."""

    message: str
    start: int
    context: str


@dataclass(slots=True)
class SaveExtractionResult:
    """Risultato complessivo di un parsing: blocchi validi ed errori riscontrati."""

    blocks: List[SaveBlock]
    errors: List[SaveBlockError]


def _canonicalize_triple_subject(triple: object) -> object:
    if not isinstance(triple, list) or len(triple) < 3:
        return triple
    subject, relation, value = triple[:3]
    suffix = triple[3:]
    if subject == "city" and relation == "name":
        return ["price", "city", value, *suffix]
    if subject == "offer" and relation == "type":
        return ["note", "assumption", f"Offerta {value}"]
    if subject == "contract_power_kW" and relation == "value":
        return ["note", "assumption", f"Potenza contrattuale {value} kW"]
    return triple


def extract_save_blocks(text: str) -> SaveExtractionResult:
    """Estrae tutti i blocchi >>> SAVE producendo triple pronte per il TripleStore.

    La funzione supporta output con testo libero prima/dopo, multipli blocchi per
    messaggio e tollera righe vuote o spaziature. I blocchi >>> CHECKLIST vengono
    ignorati. Gli errori su un blocco non impediscono l'estrazione degli altri.
    """

    blocks: List[SaveBlock] = []
    errors: List[SaveBlockError] = []

    for match in _SAVE_PATTERN.finditer(text):
        marker = match.group(1).upper()
        if marker == "CHECKLIST":
            logger.debug("Ignoro marker CHECKLIST alla posizione %s", match.start())
            continue
        block_start = match.end()
        logger.debug("Trovato blocco SAVE da posizione %s", block_start)
        payload_result = _extract_json_payload(text, block_start)
        if payload_result is None:
            err = SaveBlockError(
                message="JSON non trovato o non valido dopo >>> SAVE.",
                start=block_start,
                context=_context_snippet(text, block_start),
            )
            errors.append(err)
            logger.debug("Errore estrazione blocco alla posizione %s: %s", block_start, err.message)
            continue

        raw_json, payload, arr_start, arr_end, was_object = payload_result
        triples, block_errors = _convert_payload_to_triples(payload, block_start + arr_start, raw_json, was_object)
        errors.extend(block_errors)
        if triples:
            block = SaveBlock(triples=triples, raw_json=raw_json, start=block_start + arr_start, end=block_start + arr_end)
            blocks.append(block)
            logger.debug("Blocco SAVE valido con %s triplette", len(triples))
        else:
            logger.debug("Blocco SAVE senza triplette valide alla posizione %s", block_start)
    return SaveExtractionResult(blocks=blocks, errors=errors)


def _extract_json_payload(text: str, start: int) -> tuple[str, object, int, int, bool] | None:
    """Ricerca il primo payload JSON (array o oggetto) ben formato dopo la posizione indicata."""

    decoder = json.JSONDecoder()
    idx = start
    length = len(text)
    while idx < length:
        if text.startswith("\ufeff", idx):
            idx += 1
            continue
        if text[idx].isspace():
            idx += 1
            continue
        if text.startswith("```", idx):
            idx += 3
            while idx < length and text[idx] not in ("\n", "\r"):
                idx += 1
            continue
        break
    if idx >= length:
        return None

    if text[idx] not in "[{":
        return None

    try:
        payload, offset = decoder.raw_decode(text[idx:])
    except json.JSONDecodeError as exc:
        logger.debug("JSONDecodeError su blocco SAVE (pos=%s): %s", start + idx + exc.pos, exc.msg)
        return None

    raw_slice = text[idx: idx + offset]
    left_trim = len(raw_slice) - len(raw_slice.lstrip())
    right_trimmed = raw_slice.rstrip()
    raw_json = raw_slice[left_trim: len(right_trimmed)]

    start_offset = (idx - start) + left_trim
    end_offset = start_offset + len(raw_json)
    is_object = text[idx] == "{"
    return raw_json, payload, start_offset, end_offset, is_object
    return None


def _convert_payload_to_triples(payload: object, base_pos: int, raw_json: str, was_object: bool) -> tuple[List[Triple], List[SaveBlockError]]:
    """Converte il payload JSON in triplette, accumulando eventuali errori."""

    errors: List[SaveBlockError] = []
    if isinstance(payload, dict):
        converted = _convert_object_triplet(payload, base_pos, raw_json)
        if converted is None:
            errors.append(
                SaveBlockError(
                    message="Oggetto JSON non riconosciuto come tripletta.",
                    start=base_pos,
                    context=raw_json[:80],
                )
            )
            return [], errors
        logger.warning("Payload SAVE era un oggetto JSON: convertito in tripletta singola.")
        payload = [converted]
    elif not isinstance(payload, list):
        errors.append(
            SaveBlockError(
                message="Il contenuto di >>> SAVE deve essere un array JSON.",
                start=base_pos,
                context=raw_json[:80],
            )
        )
        return [], errors

    triples: List[Triple] = []
    for index, entry in enumerate(payload):
        entry = _canonicalize_triple_subject(entry)
        if not isinstance(entry, list):
            errors.append(
                SaveBlockError(
                    message=f"La tripla {index} non e un array JSON.",
                    start=base_pos,
                    context=json.dumps(entry, ensure_ascii=False)[:80],
                )
            )
            continue
        if not (3 <= len(entry) <= 4):
            errors.append(
                SaveBlockError(
                    message=f"La tripla {index} deve contenere 3 o 4 elementi.",
                    start=base_pos,
                    context=json.dumps(entry, ensure_ascii=False)[:80],
                )
            )
            continue
        subject, relation, value, *meta_tail = entry
        if not isinstance(subject, str) or not isinstance(relation, str):
            errors.append(
                SaveBlockError(
                    message=f"La tripla {index} richiede soggetto e relazione stringa.",
                    start=base_pos,
                    context=json.dumps(entry, ensure_ascii=False)[:80],
                )
            )
            continue
        meta = meta_tail[0] if meta_tail else None
        if meta is not None and not isinstance(meta, Mapping):
            errors.append(
                SaveBlockError(
                    message=f"La meta della tripla {index} deve essere un oggetto JSON.",
                    start=base_pos,
                    context=json.dumps(entry, ensure_ascii=False)[:80],
                )
            )
            meta = None
        triple = Triple(subject=subject, relation=relation, value=value, meta=dict(meta) if isinstance(meta, Mapping) else meta)
        triples.append(triple)
        logger.debug("Aggiunta tripletta %s -> %s", subject, relation)
    return triples, errors


def _convert_object_triplet(obj: Mapping[str, object], base_pos: int, raw_json: str) -> List[object] | None:
    subject = obj.get("subject")
    relation = obj.get("relation")
    if not isinstance(subject, str) or not isinstance(relation, str):
        return None
    value = obj.get("value")
    meta = obj.get("meta")
    if meta is not None and not isinstance(meta, Mapping):
        return None
    triple: List[object] = [subject, relation, value]
    if meta is not None:
        triple.append(dict(meta))
    return triple


def _context_snippet(text: str, pos: int, radius: int = 60) -> str:
    """Restituisce un estratto leggibile attorno alla posizione indicata."""

    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    snippet = text[start:end]
    return snippet.replace("\n", " ")


__all__ = [
    "SaveBlock",
    "SaveBlockError",
    "SaveExtractionResult",
    "extract_save_blocks",
]
