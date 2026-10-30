"""Orchestrazione della conversazione tra utente, LLM e pipeline di scheduling."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from energy_planner.llm.provider import LLMProvider
from energy_planner.prompts.loader import load_few_shots, load_reemit_save_prompt, load_system_prompt
from energy_planner.nlu.save_extractor import extract_save_blocks
from energy_planner.core.triple_store import Triple, TripleStore
from energy_planner.io.import_instance import load_instance_as_triples
from energy_planner.core.normalization import (
    SLOT_MINUTES,
    minutes_to_slot,
    normalize_context,
    parse_time,
)
from energy_planner.core.compiler import compile_instance
from energy_planner.core.validation import Activity, ValidationInput, validate, Severity
from energy_planner.core.tariffs import build_peak_constraint_hint
from energy_planner.reports.assumptions import Assumption, build_assumption_report, default_assumptions_from_context
from energy_planner.pricing.forecaster_adapter import ForecasterClient

logger = logging.getLogger(__name__)

OUT_DIR = Path("out")
INSTANCE_PATH = OUT_DIR / "instance.json"
ASSUMPTIONS_PATH = OUT_DIR / "assumptions.txt"

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
SHORT_DURATION_THRESHOLD_MIN = 15
MIN_WINDOW_MINUTES = 30
WINDOW_ASSUMPTION_NOTE = "Finestra estesa per efficacia schedulazione"

_EXPORT_REQUIREMENT_INFO: Dict[str, Tuple[str, str]] = {
    "city": (
        "Città operativa non specificata",
        "In quale città (Milano, Roma o Napoli) opera l'impianto?",
    ),
    "objective": (
        "Obiettivo di ottimizzazione (min_cost/min_peak) non scelto",
        "Preferisci ottimizzare il costo complessivo o il picco di potenza?",
    ),
    "machine": (
        "Nessuna macchina con potenza dichiarata",
        "Puoi indicare almeno una macchina e il relativo consumo in kW?",
    ),
    "workforce": (
        "Disponibilità workforce non confermata",
        "Confermi 1 persona per slot (default) oppure vuoi specificare dei turni?",
    ),
    "activity_window": (
        "Manca un'attività con durata ≥15 minuti e finestra ≥30 minuti (o lock)",
        "Descrivi un'attività con durata di almeno 30 minuti e una finestra ampia (oppure conferma un lock preciso).",
    ),
    "precedence_cycle": (
        "Le precedenze contengono un ciclo da risolvere",
        "Possiamo chiarire l'ordine tra le attività? C'è un ciclo nelle precedenze dichiarate.",
    ),
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def sanitize_llm_output(text: str, turn_idx: int) -> str:
    """Rimuove ragionamenti interni e blocchi >>> SAVE non desiderati."""

    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    if turn_idx == 0:
        marker = cleaned.lower().find(">>> save")
        if marker != -1:
            cleaned = cleaned[:marker]
    return cleaned


def extract_save_json(text: str) -> List[Any] | None:
    if not text:
        return None
    lowered = text.lower()
    marker = lowered.find(">>> save")
    if marker == -1:
        return None
    start = text.find("[", marker)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    end: Optional[int] = None
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    if end is None:
        return None
    raw = text[start:end]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _looks_incomplete(triple: List[Any]) -> bool:
    if not isinstance(triple, list) or len(triple) < 3:
        return True
    subject, relation, value = triple[:3]
    if isinstance(subject, str) and subject.startswith("activity:") and relation == "duration_min":
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return True
        return numeric <= 0
    if isinstance(subject, str) and subject.startswith("machine:") and relation == "power_kW":
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return True
        return numeric < 0
    return False


@dataclass
class ConversationConfig:
    """Configurazione dell'orchestratore."""

    prompts_path: Optional[str] = None
    stream: bool = False
    token_callback: Optional[Callable[[str], None]] = None
    export_auto: bool = False
    debug: bool = False
    log_prompts: bool = True


@dataclass
class ConversationState:
    """Stato della sessione conversazionale."""

    messages: List[Dict[str, str]] = field(default_factory=list)
    ready_for_export: bool = False
    last_reply: str = ""
    compiled_instance: Optional[Dict[str, Any]] = None
    validation_issues: List[Dict[str, Any]] = field(default_factory=list)
    assumptions_report: Optional[str] = None
    export_completed: bool = False


class Orchestrator:
    """Gestisce il dialogo con l'utente e la produzione dell'istanza JSON."""

    def __init__(
        self,
        provider: LLMProvider,
        store: TripleStore,
        config: ConversationConfig | None = None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.config = config or ConversationConfig()
        self.state = ConversationState()

        self._system_prompt = load_system_prompt(self.config.prompts_path)
        self._few_shot_messages = self._prepare_few_shots(load_few_shots(self.config.prompts_path))
        self._reemit_save_prompt = load_reemit_save_prompt(self.config.prompts_path)

        self._session_started = False
        self.session_triples: List[List[Any]] = []
        self._session_instance_path: Optional[Path] = None
        self._state_snapshot_lines: List[str] = []
        self._pending_duration_confirmations: Dict[str, float] = {}
        self._short_duration_confirmed: Set[str] = set()
        self._pending_window_adjustments: Dict[str, Dict[str, Any]] = {}
        self._export_blockers: List[str] = []
        self._export_questions: List[str] = []

        self._city: Optional[str] = None
        self._objective: Optional[str] = None
        self._has_prices = False
        self._has_workforce = False
        self._has_machine = False
        self._has_activity = False
        self._has_power_info = False
        self._machines_missing_power: List[str] = []
        self._machines_power_prompted: Set[str] = set()
        self._contractual_power_value: Optional[float] = None
        self._peak_limit_prompted = False
        self._question_snooze: Dict[str, int] = {}
        self._price_client: Optional[ForecasterClient] = None
        self._price_fetch_attempted = False
        self._price_loaded_city: Optional[str] = None

        self._export_ready = False
        self._export_prompted = False
        self._export_waiting = False
        self._export_done = False
        self._latest_summary_hint = ""
        self._latest_compiled: Optional[Dict[str, Any]] = None

        self._stream_save_buffer: str = ""
        self._stream_save_ready = False
        self._last_save_block: Optional[str] = None
        self._turn_index = 0
        self._log_prompts = bool(self.config.log_prompts)
        self._initialize_session_triples()
        self._seed_history()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def _initialize_session_triples(self) -> None:
        """Precarica le triplette di sessione da file se disponibili."""
        self.session_triples = []
        self._state_snapshot_lines = []
        self._session_instance_path = self._resolve_session_instance_path()
        if not self._session_instance_path:
            return

        try:
            triples = load_instance_as_triples(str(self._session_instance_path))
        except Exception as exc:  # pragma: no cover - difensivo
            logger.warning("Impossibile caricare l'istanza di sessione da %s: %s", self._session_instance_path, exc)
            return

        self.session_triples = triples
        triple_objects: List[Triple] = []
        for entry in triples:
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            subject, relation, value = entry[:3]
            triple_objects.append(Triple(subject=str(subject), relation=str(relation), value=value))

        if triple_objects:
            try:
                self.store.ingest(triple_objects)
            except Exception as exc:  # pragma: no cover - difensivo
                logger.warning("Ingest pre-caricata fallita: %s", exc)
            else:
                self._update_flags()

        summary = self._compose_session_summary(triples)
        if summary:
            print(f"[STATE] {summary}")
            logger.info("Sessione caricata: %s", summary)

        self._state_snapshot_lines = self._format_session_state_lines(triples, summary)

    def _resolve_session_instance_path(self) -> Optional[Path]:
        """Determina il percorso dell'istanza di sessione da caricare, se esiste."""
        candidates: List[Path] = []
        env_path = os.environ.get("SESSION_INSTANCE_PATH")
        if env_path:
            candidates.append(Path(env_path).expanduser())
        candidates.append(Path("data/session/instance.json"))

        for candidate in candidates:
            if candidate and candidate.is_file():
                return candidate
        return None

    def _compose_session_summary(self, triples: Sequence[Sequence[Any]]) -> str:
        slot_minutes = next(
            (entry[2] for entry in triples if isinstance(entry, Sequence) and len(entry) >= 3 and entry[0] == "time" and entry[1] == "slot_minutes"),
            None,
        )
        objective = next(
            (entry[2] for entry in triples if isinstance(entry, Sequence) and len(entry) >= 3 and entry[0] == "objective" and entry[1] == "primary"),
            None,
        )
        machine_ids = {
            str(entry[0]).split(":", 1)[1]
            for entry in triples
            if isinstance(entry, Sequence) and len(entry) >= 3 and str(entry[0]).startswith("machine:") and entry[1] == "name"
        }
        activity_ids = {
            str(entry[0]).split(":", 1)[1]
            for entry in triples
            if isinstance(entry, Sequence) and len(entry) >= 3 and str(entry[0]).startswith("activity:") and entry[1] == "duration_min"
        }
        parts: List[str] = []
        if slot_minutes is not None:
            parts.append(f"slot={slot_minutes}min")
        if machine_ids:
            parts.append(f"macchine={len(machine_ids)}")
        if activity_ids:
            parts.append(f"attivita={len(activity_ids)}")
        if objective:
            parts.append(f"obiettivo={objective}")
        return f"Sessione pre-caricata: {', '.join(parts)}" if parts else ""

    def _format_session_state_lines(self, triples: Sequence[Sequence[Any]], summary: str) -> List[str]:
        lines: List[str] = []
        if summary:
            lines.append(summary)
        for entry in triples:
            if not isinstance(entry, Sequence) or len(entry) < 3:
                continue
            subject, relation, value = entry[:3]
            lines.append(f"{subject} | {relation} | {self._compact_state_value(value)}")
        return lines

    @staticmethod
    def _compact_state_value(value: Any) -> str:
        if isinstance(value, list):
            if not value:
                return "[]"
            if len(value) <= 8 and all(not isinstance(item, (dict, list)) for item in value):
                return "[" + ", ".join(str(item) for item in value) + "]"
            return f"[{len(value)} valori]"
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):  # pragma: no cover - difensivo
                return str(value)
        return str(value)

    def start_session(self) -> str:
        if self._session_started:
            raise RuntimeError("La sessione e gia stata avviata.")
        self._session_started = True
        logger.info("Sessione avviata con provider %s", self.provider.name())
        return self._produce_reply()

    def handle_user_message(self, user_text: str) -> str:
        if not self._session_started:
            self.start_session()

        if self._export_waiting and not self._export_done:
            decision = self._interpret_export_response(user_text)
            if decision == "decline":
                logger.info("Export rimandato dall'utente")
                self._export_waiting = False
                self._export_prompted = False
            else:
                export_message = self._perform_export()
                self.state.messages.append({"role": "assistant", "content": export_message})
                self.state.last_reply = export_message
                return export_message

        self.state.messages.append({"role": "user", "content": user_text})
        if self._log_prompts:
            logger.debug("Messaggio utente: %s", user_text)
        else:
            logger.debug("Messaggio utente ricevuto (logging disabilitato).")
        normalized = (user_text or "").strip().lower()
        if self._should_trigger_export(normalized):
            logger.info("Export eseguito su richiesta esplicita dell'utente.")
            export_message = self._perform_export()
            self.state.messages.append({"role": "assistant", "content": export_message})
            self.state.last_reply = export_message
            self._turn_index += 1
            return export_message
        return self._produce_reply()

    def current_state(self) -> ConversationState:
        return self.state

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------
    def _produce_reply(self) -> str:
        state_hint = self._build_state_hint()
        hint_message = {"role": "system", "content": state_hint}
        self.state.messages.append(hint_message)

        try:
            reply_text = self._call_provider()
            reply_text = sanitize_llm_output(reply_text, self._turn_index)
            self.state.messages.append({"role": "assistant", "content": reply_text})
            if self._log_prompts:
                logger.debug("Risposta assistente: %s", reply_text)
            else:
                logger.debug("Risposta assistente registrata (logging disabilitato).")
            reply_text = self._process_assistant_reply(reply_text)
            self.state.last_reply = reply_text
        finally:
            self.state.messages.remove(hint_message)

        self._maybe_refresh_pipeline_state()
        self._turn_index += 1
        return reply_text

    def _call_provider(self) -> str:
        response = self.provider.complete(self.state.messages, stream=self.config.stream)
        if not self.config.stream:
            return str(response)
        self._reset_stream_state()
        collected: List[str] = []
        for chunk in response:  # type: ignore[union-attr]
            collected.append(chunk)
            if self.config.token_callback:
                self.config.token_callback(chunk)
            self._update_stream_buffer(chunk)
        return "".join(collected)

    def _process_assistant_reply(self, reply_text: str) -> str:
        has_user_message = any(msg.get("role") == "user" for msg in self.state.messages[:-1])
        if self._turn_index == 0 or not has_user_message:
            if self.config.stream:
                self._reset_stream_state()
            return reply_text
        target_text = reply_text
        if self.config.stream:
            if not self._stream_save_buffer:
                self._stream_save_buffer = reply_text
            if not self._stream_save_ready and not self._has_complete_save_array(self._stream_save_buffer):
                logger.debug("Streaming: blocco SAVE non ancora completo, attendo ulteriori token.")
                return reply_text
            if self._stream_save_ready:
                target_text = self._stream_save_buffer
            self._reset_stream_state()

        raw_triples = extract_save_json(target_text)
        if raw_triples is not None:
            filtered_triples = [
                triple for triple in raw_triples if isinstance(triple, list) and not _looks_incomplete(triple)
            ]
            if not filtered_triples:
                return
            if filtered_triples != raw_triples:
                lower = target_text.lower()
                marker = lower.find(">>> save")
                if marker != -1:
                    array_start = target_text.find("[", marker)
                    if array_start != -1:
                        depth = 0
                        in_string = False
                        escaped = False
                        array_end: Optional[int] = None
                        for idx in range(array_start, len(target_text)):
                            ch = target_text[idx]
                            if in_string:
                                if escaped:
                                    escaped = False
                                elif ch == "\\":
                                    escaped = True
                                elif ch == '"':
                                    in_string = False
                                continue
                            if ch == '"':
                                in_string = True
                                continue
                            if ch == "[":
                                depth += 1
                            elif ch == "]":
                                depth -= 1
                                if depth == 0:
                                    array_end = idx + 1
                                    break
                        if array_end is not None:
                            new_json = json.dumps(filtered_triples, ensure_ascii=False)
                            target_text = target_text[:array_start] + new_json + target_text[array_end:]
                            reply_text = target_text

        extraction = extract_save_blocks(target_text)
        if extraction.errors and reply_text.strip():
            logger.warning("Parsing SAVE fallito: %s", [error.message for error in extraction.errors])
            if self._retry_save_blocks(reply_text):
                return
        for block in extraction.blocks:
            prepared_triples = self._prepare_triples_for_store(block.triples)
            if prepared_triples:
                self.store.ingest(prepared_triples)
                self._last_save_block = block.raw_json
        for error in extraction.errors:
            logger.warning("Parsing SAVE fallito (pos=%s): %s", error.start, error.message)
        self._update_flags()
        if self.state.messages:
            self.state.messages[-1]["content"] = reply_text
        return reply_text

    def _reset_stream_state(self) -> None:
        self._stream_save_buffer = ""
        self._stream_save_ready = False

    def _update_stream_buffer(self, chunk: str) -> None:
        self._stream_save_buffer += chunk
        if not self._stream_save_ready and self._has_complete_save_array(self._stream_save_buffer):
            self._stream_save_ready = True

    @staticmethod
    def _has_complete_save_array(text: str) -> bool:
        lowered = text.lower()
        marker_idx = lowered.rfind(">>> save")
        if marker_idx == -1:
            return True
        segment = text[marker_idx:]
        bracket_found = False
        depth = 0
        in_string = False
        escape = False
        for char in segment:
            if not bracket_found:
                if char == "[":
                    bracket_found = True
                    depth = 1
                continue
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return True
        return False

    # ------------------------------------------------------------------
    # Triple pre-processing hooks
    # ------------------------------------------------------------------
    def _prepare_triples_for_store(self, triples: Sequence[Triple]) -> List[Triple]:
        prepared: List[Triple] = []
        add_window_assumption = False
        for triple in triples:
            processed, assumption_needed = self._handle_special_triple(triple)
            if processed is None:
                continue
            if isinstance(processed, list):
                prepared.extend(processed)
            else:
                prepared.append(processed)
            add_window_assumption = add_window_assumption or assumption_needed
        if add_window_assumption:
            prepared.append(Triple(subject="note", relation="assumption", value=WINDOW_ASSUMPTION_NOTE))
        return prepared

    def _handle_special_triple(self, triple: Triple) -> tuple[Any, bool]:
        subject = triple.subject
        relation = triple.relation
        if not isinstance(subject, str):
            return triple, False
        if subject.startswith("activity:"):
            activity_id = subject.split(":", 1)[1]
            if relation == "duration_min":
                return self._handle_activity_duration(activity_id, triple)
            if relation == "window" and isinstance(triple.value, Mapping):
                return self._handle_activity_window(activity_id, triple)
        return triple, False

    def _handle_activity_duration(self, activity_id: str, triple: Triple) -> tuple[Optional[Triple], bool]:
        try:
            minutes = float(triple.value)
        except (TypeError, ValueError):
            return triple, False

        if minutes < SHORT_DURATION_THRESHOLD_MIN:
            meta_warning = ""
            if isinstance(triple.meta, dict):
                meta_warning = str(triple.meta.get("warning", "")).strip().lower()
            if meta_warning == "durata molto breve" or activity_id in self._short_duration_confirmed:
                if not isinstance(triple.meta, dict):
                    triple.meta = {"warning": "durata molto breve"}
                else:
                    triple.meta["warning"] = "durata molto breve"
                self._pending_duration_confirmations.pop(activity_id, None)
                self._short_duration_confirmed.add(activity_id)
                return triple, False
            self._pending_duration_confirmations[activity_id] = minutes
            logger.info("Durata %s min per l'attivita %s richiede conferma esplicita.", minutes, activity_id)
            return None, False

        # Durata accettabile: nessuna conferma necessaria
        self._pending_duration_confirmations.pop(activity_id, None)
        self._short_duration_confirmed.discard(activity_id)
        return triple, False

    def _handle_activity_window(self, activity_id: str, triple: Triple) -> tuple[Optional[Triple], bool]:
        value = triple.value
        try:
            start_str = str(value["start"])
            end_str = str(value["end"])
            start_minute = parse_time(start_str)
            end_minute = parse_time(end_str)
        except (KeyError, ValueError, TypeError):
            return triple, False

        if end_minute < start_minute:
            end_minute = start_minute

        width_minutes = end_minute - start_minute
        start_slot = minutes_to_slot(start_minute)
        end_slot = minutes_to_slot(end_minute)

        if width_minutes <= SLOT_MINUTES:
            self._pending_window_adjustments[activity_id] = self._build_window_prompt_info(
                activity_id,
                start_minute,
                end_minute,
                start_slot,
                end_slot,
            )
            logger.info("Finestra di %s troppo stretta (%s minuti): richiesta estensione.", activity_id, width_minutes)
            return None, False

        was_pending = activity_id in self._pending_window_adjustments
        if was_pending:
            self._pending_window_adjustments.pop(activity_id, None)
        return triple, was_pending

    def _build_window_prompt_info(
        self,
        activity_id: str,
        start_minute: int,
        end_minute: int,
        start_slot: int,
        end_slot: int,
    ) -> Dict[str, Any]:
        option_keep_start = self._format_window_interval(
            start_minute,
            start_minute + 30,
        )
        option_expand_both = self._format_window_interval(
            max(0, start_minute - 15),
            start_minute + 45,
        )
        info: Dict[str, Any] = {
            "activity": activity_id,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "start_slot": start_slot,
            "end_slot": end_slot,
            "start_label": f"{self._minutes_to_hhmm(start_minute)}-{self._minutes_to_hhmm(end_minute)}",
            "option_keep_start": option_keep_start,
            "option_expand_both": option_expand_both,
        }
        return info

    def _format_window_interval(self, start_minute: int, end_minute: int) -> str:
        start_minute = max(0, start_minute)
        end_minute = max(start_minute + SLOT_MINUTES, end_minute)
        start_slot = minutes_to_slot(start_minute)
        end_slot = minutes_to_slot(end_minute)
        return f"{self._minutes_to_hhmm(start_minute)}-{self._minutes_to_hhmm(end_minute)} (slot {start_slot}-{end_slot})"

    @staticmethod
    def _minutes_to_hhmm(total_minutes: int) -> str:
        total_minutes = max(0, total_minutes)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02d}:{minutes:02d}"

    # ------------------------------------------------------------------
    # Export completeness checks
    # ------------------------------------------------------------------
    def _collect_activity_requirements(
        self,
        compiled: Optional[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Set[str], int]:
        if compiled:
            slot_minutes = int(compiled.get("time", {}).get("slot_minutes", SLOT_MINUTES))
            locks_set = {
                (lock.get("activity").split(":", 1)[1] if isinstance(lock.get("activity"), str) and ":" in lock.get("activity") else str(lock.get("activity")))
                for lock in compiled.get("locks", []) or []
                if isinstance(lock, Mapping) and lock.get("activity")
            }
            activities_info: List[Dict[str, Any]] = []
            for item in compiled.get("activities", []) or []:
                act_id = str(item.get("id", "")).strip()
                if not act_id:
                    continue
                try:
                    duration_slots = int(item.get("duration_slots", 0))
                except (TypeError, ValueError):
                    duration_slots = 0
                duration_min = duration_slots * slot_minutes
                window_slots = item.get("window_slots", [0, 0])
                if isinstance(window_slots, list) and len(window_slots) == 2:
                    try:
                        window_span = max(0, (int(window_slots[1]) - int(window_slots[0])) * slot_minutes)
                    except (TypeError, ValueError):
                        window_span = None
                else:
                    window_span = None
                successors: List[str] = []
                for target in item.get("precedences", []) or []:
                    successor = str(target)
                    if successor.startswith("activity:"):
                        successor = successor.split(":", 1)[1]
                    successors.append(successor)
                activities_info.append(
                    {
                        "id": act_id,
                        "duration_min": duration_min,
                        "window_minutes": window_span,
                        "succ": successors,
                    }
                )
            return activities_info, locks_set, slot_minutes

        activities: Dict[str, Dict[str, Any]] = {}
        for triple in self.store.query(subject_prefix="activity:"):
            activity_id = triple.subject.split(":", 1)[1]
            entry = activities.setdefault(
                activity_id,
                {
                    "id": activity_id,
                    "duration_min": None,
                    "window_minutes": None,
                    "succ": set(),
                },
            )
            relation = triple.relation
            value = triple.value
            if relation in {"duration_min", "duration_minutes"}:
                try:
                    entry["duration_min"] = float(value)
                except (TypeError, ValueError):
                    continue
            elif relation in {"duration_slots", "duration_in_slots"}:
                try:
                    entry["duration_min"] = float(value) * SLOT_MINUTES
                except (TypeError, ValueError):
                    continue
            elif relation == "window":
                if isinstance(value, Mapping) and "start" in value and "end" in value:
                    try:
                        start = parse_time(str(value["start"]))
                        end = parse_time(str(value["end"]))
                        entry["window_minutes"] = max(0, end - start)
                    except ValueError:
                        continue
            elif relation == "window_slots" and isinstance(value, list) and len(value) == 2:
                try:
                    start_slot = int(value[0])
                    end_slot = int(value[1])
                    entry["window_minutes"] = max(0, (end_slot - start_slot) * SLOT_MINUTES)
                except (TypeError, ValueError):
                    continue
            elif relation == "precedes":
                targets = value if isinstance(value, list) else [value]
                for target in targets:
                    successor = str(target)
                    if successor.startswith("activity:"):
                        successor = successor.split(":", 1)[1]
                    entry["succ"].add(successor)

        locks_set: Set[str] = set()
        for triple in self.store.query(subject_prefix="lock"):
            if triple.relation != "start_at" or not isinstance(triple.value, Mapping):
                continue
            activity_ref = triple.value.get("activity")
            if isinstance(activity_ref, str):
                locks_set.add(activity_ref.split(":", 1)[1] if ":" in activity_ref else activity_ref)

        activities_info = []
        for entry in activities.values():
            activities_info.append(
                {
                    "id": entry["id"],
                    "duration_min": entry["duration_min"],
                    "window_minutes": entry["window_minutes"],
                    "succ": sorted(entry["succ"]),
                }
            )
        return activities_info, locks_set, SLOT_MINUTES

    @staticmethod
    def _detect_precedence_cycle(activities: Sequence[Dict[str, Any]]) -> bool:
        graph: Dict[str, List[str]] = {}
        for activity in activities:
            graph[activity["id"]] = list(activity.get("succ") or [])

        visited: Dict[str, int] = {}

        def visit(node: str) -> bool:
            state = visited.get(node, 0)
            if state == 1:
                return True
            if state == 2:
                return False
            visited[node] = 1
            for successor in graph.get(node, []):
                if successor not in graph:
                    continue
                if visit(successor):
                    return True
            visited[node] = 2
            return False

        for node in graph:
            if visit(node):
                return True
        return False

    def compute_missing_for_export(
        self,
        compiled: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[str], List[str]]:
        missing: List[str] = []

        if not self._city:
            missing.append("city")
        if not self._objective:
            missing.append("objective")

        if compiled:
            machines_with_power = [
                machine
                for machine in compiled.get("machines") or []
                if _safe_float(machine.get("power_kW")) > 0.0
            ]
            workforce_present = bool(compiled.get("workforce"))
        else:
            machines_with_power = []
            for triple in self.store.query(subject_prefix="machine:"):
                if triple.relation != "power_kW":
                    continue
                try:
                    if float(triple.value) > 0:
                        machines_with_power.append(triple)
                        break
                except (TypeError, ValueError):
                    continue
            workforce_present = self._has_workforce

        if not machines_with_power:
            missing.append("machine")
        if not workforce_present:
            missing.append("workforce")

        activities_info, locks_set, _ = self._collect_activity_requirements(compiled)
        valid_activity = False
        for activity in activities_info:
            duration = activity.get("duration_min")
            if duration is None or duration < SHORT_DURATION_THRESHOLD_MIN:
                continue
            if activity["id"] in locks_set:
                valid_activity = True
                break
            window_minutes = activity.get("window_minutes")
            if window_minutes is not None and window_minutes >= MIN_WINDOW_MINUTES:
                valid_activity = True
                break
        if not activities_info or not valid_activity:
            missing.append("activity_window")

        if activities_info and self._detect_precedence_cycle(activities_info):
            missing.append("precedence_cycle")

        unique_missing: List[str] = []
        seen: Set[str] = set()
        for code in missing:
            if code not in seen:
                unique_missing.append(code)
                seen.add(code)

        questions: List[str] = []
        for code in unique_missing:
            info = _EXPORT_REQUIREMENT_INFO.get(code)
            if info and info[1]:
                questions.append(info[1])
            if len(questions) >= 2:
                break

        return unique_missing, questions

    # ------------------------------------------------------------------
    # State & hinting
    # ------------------------------------------------------------------
    def _build_state_hint(self) -> str:
        self._decay_question_snooze()
        hints = ["## Stato interno (non mostrare all'utente)"]
        if self._state_snapshot_lines:
            hints.append("I dati in [STATE] sono confermati e non necessitano deduzioni.")
            hints.append("[STATE]")
            hints.extend(self._state_snapshot_lines)
            hints.append("[/STATE]")
        if self._pending_duration_confirmations:
            hints.append(
                "Durate inferiori a 15 minuti rilevate: chiedi la micro-conferma \"La durata è inferiore a 15 minuti. Confermi (schedulazione poco efficace), oppure imposto 30 minuti come default?\" e attendi risposta."
            )
            for activity_id, minutes in self._pending_duration_confirmations.items():
                hints.append(f"- {activity_id}: proposta {minutes:g} minuti; salva solo dopo conferma e usa meta warning se resta <15.")
        if self._pending_window_adjustments:
            hints.append(
                "Finestre troppo strette (larghezza 1 slot) rilevate: proponi di allargarle offrendo sia [start, start+30'] sia [start-15', start+45'], mostrando anche gli slot."
            )
            for activity_id, info in self._pending_window_adjustments.items():
                hints.append(
                    f"- {activity_id}: finestra attuale {info['start_label']} (slot {info['start_slot']}-{info['end_slot']}); opzioni: {info['option_keep_start']} oppure {info['option_expand_both']}."
                )
        if self._export_blockers:
            hints.append("Requisiti mancanti per poter esportare:")
            for code in self._export_blockers:
                description = _EXPORT_REQUIREMENT_INFO.get(code, (code, ""))[0]
                hints.append(f"- {description}")
        question_lines: List[str] = []
        if self._export_questions:
            for idx, question in enumerate(self._export_questions):
                code = self._export_blockers[idx] if idx < len(self._export_blockers) else None
                if code and self._question_snooze.get(code, 0) > 0:
                    continue
                question_lines.append(f"? {question}")
                if code:
                    current = self._question_snooze.get(code, 0)
                    self._question_snooze[code] = max(current, 2)
        if question_lines:
            hints.append("Formula in chiusura le seguenti domande (una per turno) per colmare i dati mancanti:")
            hints.extend(question_lines)
        if self._export_ready and not self._export_done:
            if self._latest_summary_hint:
                hints.append(f"Riepilogo suggerito: {self._latest_summary_hint}")
            hints.append("Chiedi all'utente se posso esportare ora; proponi export e riepilogo conciso.")
            if not self._export_waiting:
                self._export_waiting = True
            if not self._export_prompted:
                self._export_prompted = True
        else:
            gaps = self._describe_gaps()
            if gaps:
                hints.append("Attivita da completare:")
                hints.extend(f"- {item}" for item in gaps)
            if self._city and self._city.lower() not in {"milano", "roma", "napoli"}:
                hints.append(
                    f"Citta indicata '{self._city}' non supportata: ricorda di proporre la citta piu vicina tra Milano, Roma o Napoli e di salvare una nota di assunzione (SIMULAZIONE)."
                )
            new_missing = [m for m in self._machines_missing_power if m not in self._machines_power_prompted]
            if new_missing:
                hints.append(f"Macchine senza potenza dichiarata ({', '.join(new_missing)}): chiedi 'Vuoi indicare la potenza ora?' e ricorda che il dato e aggiornabile.")
                self._machines_power_prompted.update(new_missing)
            if self._objective == "min_peak" and self._contractual_power_value and not self._peak_limit_prompted:
                hints.append(f"Potenza contrattuale {self._contractual_power_value:g} kW nota: proponi un vincolo di picco <= valore dichiarato.")
                self._peak_limit_prompted = True
        hints.append("Massimo due domande per turno; salva sempre i fatti certi con >>> SAVE.")
        if not self._has_power_info:
            hints.append("Ricorda di annotare l'assenza della potenza contrattuale con una assumption.")
        hints.append("Quando comunichi finestre temporali, usa sempre il formato 'HH:MM-HH:MM (slot X-Y)'.")
        return "\n".join(hints)

    def _decay_question_snooze(self) -> None:
        to_remove: List[str] = []
        for code, turns in list(self._question_snooze.items()):
            if code not in self._export_blockers:
                to_remove.append(code)
                continue
            if turns > 0:
                self._question_snooze[code] = turns - 1
        for code in to_remove:
            self._question_snooze.pop(code, None)

    def _describe_gaps(self) -> List[str]:
        gaps: List[str] = []
        if not self._city:
            gaps.append("Richiedi la citta (Milano, Roma, Napoli). Se viene proposta una citta diversa, proponi quella supportata piu vicina (SIMULAZIONE) e salva l assunzione.")
        if not self._objective:
            gaps.append("Chiedi l'offerta (Fix/Flex/PLACET) e imposta l'obiettivo.")
        if not self._has_prices:
            gaps.append("Prezzi mancanti: chiedi di scegliere tra A) incollare i 24 valori €/kWh, B) usare la serie flat 0.25 SIMULAZIONE.")
        if not self._has_workforce:
            gaps.append("Raccogli turni workforce o conferma il default 1 persona per slot.")
        if not self._has_machine:
            gaps.append("Elenca le macchine con potenza dichiarata.")
        if not self._has_activity:
            gaps.append("Definisci le attivita con durata, finestra e risorse.")
        return gaps

    def _update_flags(self) -> None:
        self._city = next((triple.value for triple in self.store.query(subject_prefix="price", relation="city")), None)
        objective = next((str(triple.value).lower() for triple in self.store.query(subject_prefix="objective", relation="primary")), None)
        if objective:
            self._objective = objective
        self._has_prices = any(True for _ in self.store.query(subject_prefix="price", relation="per_slot")) \
            or any(True for _ in self.store.query(subject_prefix="price", relation="per_hour"))
        self._has_workforce = any(True for _ in self.store.query(subject_prefix="workforce"))
        self._has_machine = any(True for _ in self.store.query(subject_prefix="machine:"))
        self._has_activity = any(True for _ in self.store.query(subject_prefix="activity:"))
        self._has_power_info = any(
            isinstance(triple.value, str) and "potenza" in triple.value.lower()
            for triple in self.store.query(subject_prefix="note", relation="warning")
        )
        self._machines_missing_power = self._collect_machines_without_power()
        self._machines_power_prompted.intersection_update(self._machines_missing_power)

    def _ensure_pricing_for_export(self) -> bool:
        """Recupera e memorizza i prezzi orari prima dell'export."""
        city_value = self._city
        if not city_value:
            return False
        city_str = str(city_value)

        per_hour_triples = list(self.store.query(subject_prefix="price", relation="per_hour"))
        existing_cities = {str(triple.value) for triple in self.store.query(subject_prefix="price", relation="city")}
        if per_hour_triples:
            if self._price_loaded_city == city_str:
                return False
            if self._price_loaded_city is None and city_str in existing_cities:
                return False

        if self._price_client is None:
            try:
                self._price_client = ForecasterClient()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Impossibile inizializzare ForecasterClient: %s", exc)
                self._price_fetch_attempted = True
                return False

        try:
            forecast = self._price_client.predict_hourly(city_str, hours=24)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Recupero prezzi automatico fallito per %s: %s", city_str, exc)
            self._price_fetch_attempted = True
            return False

        per_hour = list(forecast.get("per_hour") or [])
        if not per_hour:
            logger.warning("Serie prezzi vuota dal forecaster per %s", city_str)
            self._price_fetch_attempted = True
            return False

        triples_to_emit: List[List[Any]] = []
        forecast_city = str(forecast.get("city") or city_str)
        if forecast_city not in existing_cities:
            triples_to_emit.append(["price", "city", forecast_city])
        triples_to_emit.append(["price", "per_hour", per_hour])

        meta = forecast.get("meta") or {}
        if meta.get("simulazione"):
            assumption_text = "Prezzi interni previsti per la città selezionata"
            already_present = any(
                str(triple.value) == assumption_text
                for triple in self.store.query(subject_prefix="note", relation="assumption")
            )
            if not already_present:
                triples_to_emit.append(["note", "assumption", assumption_text])

        triple_objects = [Triple(subject=item[0], relation=item[1], value=item[2]) for item in triples_to_emit]
        prepared_triples = self._prepare_triples_for_store(triple_objects)
        if not prepared_triples:
            self._price_fetch_attempted = True
            return False

        self.store.ingest(prepared_triples)
        self._update_flags()
        self._last_save_block = json.dumps(triples_to_emit, ensure_ascii=False, indent=2)
        self._price_fetch_attempted = True
        self._price_loaded_city = forecast_city
        return True

    # ------------------------------------------------------------------
    # Pipeline evaluation
    # ------------------------------------------------------------------
    def _maybe_refresh_pipeline_state(self) -> None:
        pre_blockers, pre_questions = self.compute_missing_for_export(None)
        self._export_blockers = pre_blockers
        self._export_questions = pre_questions
        if not (self._city and self._has_activity):
            self.state.ready_for_export = False
            self._export_ready = False
            return
        try:
            normalized = self._normalize()
            compiled = compile_instance(self.store)
            validation = self._validate(compiled)

            issues = [
                {"severity": issue.severity.value, "message": issue.message, "suggestion": issue.suggestion}
                for issue in validation.issues
            ]
            self.state.validation_issues = issues
            self.state.compiled_instance = compiled

            assumptions_text: List[str] = []
            assumptions_text.extend(compiled.get("assumptions", []))
            assumptions_text.extend(normalized.assumptions)

            unknown_power = [machine['id'] for machine in compiled.get('machines', []) if float(machine.get('power_kW', 0)) == 0]
            assumption_entries: List[Assumption] = [
                Assumption("Assunzioni", text) for text in assumptions_text if text
            ]
            auto_assumptions = default_assumptions_from_context(
                used_flat_prices=any('flat' in t.lower() for t in normalized.assumptions),
                used_default_workforce=any('workforce' in t.lower() and 'default' in t.lower() for t in normalized.assumptions),
                machines_with_unknown_power=unknown_power or None,
            )
            assumption_entries.extend(auto_assumptions)
            self.state.assumptions_report = build_assumption_report(assumption_entries)

            dataset_ready = self._dataset_ready(compiled, validation)
            blockers, questions = self.compute_missing_for_export(compiled)
            self._export_blockers = blockers
            self._export_questions = questions
            dataset_ready = dataset_ready and not blockers
            self.state.ready_for_export = dataset_ready
            self._has_prices = bool(compiled.get("pricing"))
            self._has_workforce = bool(compiled.get("workforce"))
            self._latest_compiled = compiled

            if dataset_ready and not self._export_done:
                self._export_ready = True
                self._latest_summary_hint = self._compose_summary_hint(compiled)
            else:
                self._export_ready = False
                if not dataset_ready:
                    self._latest_summary_hint = ""
                    self._export_prompted = False
                    self._export_waiting = False
                    self.state.export_completed = False
        except Exception as exc:  # pragma: no cover
            logger.exception("Errore durante la pipeline di compilazione: %s", exc)
            self.state.compiled_instance = None
            self.state.validation_issues = [
                {"severity": "ERROR", "message": str(exc), "suggestion": "Verificare i dati raccolti."}
            ]
            self.state.assumptions_report = None
            self.state.ready_for_export = False
            self._export_ready = False
            self._export_waiting = False
            self._export_prompted = False
            self.state.export_completed = False
            self._export_blockers = pre_blockers
            self._export_questions = pre_questions

    def _normalize(self):
        horizon = 24
        for triple in self.store.query(subject_prefix="horizon", relation="hours"):
            try:
                value = float(triple.value)
            except (TypeError, ValueError):
                continue
            if value > 0:
                horizon = int(value)
                break
        per_hour = next(
            (
                triple.value
                for triple in self.store.query(subject_prefix="price", relation="per_hour")
                if isinstance(triple.value, list)
            ),
            None,
        )
        shifts = [
            triple.value
            for triple in self.store.query(subject_prefix="workforce", relation="shift")
            if isinstance(triple.value, Mapping)
        ]
        return normalize_context(
            horizon_hours=horizon,
            per_hour_prices=per_hour,
            workforce_shifts=shifts,
        )

    def _validate(self, compiled: Dict[str, Any]):
        slot_minutes = int(compiled["time"]["slot_minutes"])
        activities: List[Activity] = []
        for item in compiled.get("activities", []):
            duration_slots = int(item["duration_slots"])
            window_slots = item.get("window_slots", [0, 0])
            earliest_slot = int(window_slots[0]) if window_slots else 0
            latest_slot = int(window_slots[1]) if isinstance(window_slots, list) and len(window_slots) > 1 else earliest_slot
            window_end_slot = item.get("window_end_slot")
            if window_end_slot is not None:
                try:
                    end_slot = int(window_end_slot)
                except (TypeError, ValueError):
                    end_slot = latest_slot + duration_slots
            else:
                end_slot = latest_slot + duration_slots
            activities.append(
                Activity(
                    name=item.get("id", item.get("name", "activity")),
                    duration_minutes=duration_slots * slot_minutes,
                    window_start=earliest_slot * slot_minutes,
                    window_end=end_slot * slot_minutes,
                    employees=float(item.get("employees", 0)),
                    machine=item.get("requires_machine"),
                    precedences=item.get("precedences", []),
                )
            )
        machine_powers = {
            machine["id"]: float(machine.get("power_kW", 0))
            for machine in compiled.get("machines", [])
        }
        contractual = self._extract_contractual_power()
        self._contractual_power_value = contractual
        if contractual is not None:
            assumptions_list = compiled.setdefault("assumptions", [])
            message = build_peak_constraint_hint(contractual, None) or "Potenza contrattuale registrata."
            if message not in assumptions_list:
                assumptions_list.append(message)
        return validate(
            ValidationInput(
                activities=activities,
                workforce_per_slot=compiled.get("workforce", []),
                price_per_slot=compiled.get("pricing", []),
                objective=compiled.get("objective", "min_cost"),
                machine_powers=machine_powers,
                contractual_power=contractual,
                enforce_power_hard=True,
            )
        )

    def _dataset_ready(self, compiled: Dict[str, Any], validation) -> bool:
        if not self._city or not self._objective:
            return False
        pricing = compiled.get("pricing", [])
        workforce = compiled.get("workforce", [])
        if not pricing or not workforce:
            return False
        activities = compiled.get("activities", [])
        valid_activity = False
        for item in activities:
            duration_slots = int(item.get("duration_slots", 0))
            window_slots = item.get("window_slots", [])
            employees = float(item.get("employees", 0))
            if duration_slots <= 0 or employees <= 0:
                continue
            if not isinstance(window_slots, list) or len(window_slots) != 2:
                continue
            if int(window_slots[1]) < int(window_slots[0]):
                continue
            valid_activity = True
        if not valid_activity:
            return False
        for issue in validation.issues:
            if issue.severity == Severity.ERROR:
                return False
        return True

    def _extract_contractual_power(self) -> Optional[float]:
        for triple in self.store.query(subject_prefix="note", relation="warning"):
            if not isinstance(triple.value, str):
                continue
            lower = triple.value.lower()
            if "potenza" in lower and "kw" in lower:
                numbers = [float(part.replace(",", ".")) for part in re.findall(r"\d+[\.,]?\d*", lower)]
                if numbers:
                    return numbers[0]
        return None

    def _collect_machines_without_power(self) -> List[str]:
        missing: List[str] = []
        machines: Dict[str, Dict[str, Any]] = {}
        for triple in self.store.query(subject_prefix="machine:"):
            machine_id = triple.subject.split(":", 1)[1]
            entry = machines.setdefault(machine_id, {"power": None})
            if triple.relation == "power_kW":
                try:
                    entry["power"] = float(triple.value)
                except (TypeError, ValueError):
                    entry["power"] = 0.0
        for machine_id, data in machines.items():
            power = data.get("power")
            if power is None or float(power) == 0.0:
                missing.append(machine_id)
        return sorted(missing)

    # ------------------------------------------------------------------
    # Export management
    # ------------------------------------------------------------------
    def _interpret_export_response(self, user_text: str) -> str:
        text = (user_text or "").strip().lower()
        if not text:
            return "accept"
        affirmatives = {"si", "yes", "ok", "vai", "procedi", "salva", "esporta", "export"}
        negatives = {"no", "non ancora", "aspetta", "piu tardi", "rimanda"}
        if text in affirmatives or text.startswith("va bene"):
            return "accept"
        if any(token in text for token in negatives):
            return "decline"
        return "accept"

    def _should_trigger_export(self, normalized_text: str) -> bool:
        if self._export_done:
            return False
        if not normalized_text:
            return False
        if not (self._export_ready or self.state.ready_for_export):
            return False
        if not self._latest_compiled:
            return False
        negative_tokens = ("non salv", "non esport", "non export", "aspetta", "piu tardi")
        if any(token in normalized_text for token in negative_tokens):
            return False
        keywords = (
            "salva",
            "salvare",
            "salvalo",
            "salvala",
            "salvali",
            "esporta",
            "esportazione",
            "export",
            "instance.json",
        )
        return any(keyword in normalized_text for keyword in keywords)

    def _perform_export(self) -> str:
        pricing_updated = self._ensure_pricing_for_export()
        if pricing_updated:
            self._maybe_refresh_pipeline_state()

        if not self._latest_compiled:
            raise RuntimeError("Export richiesto senza istanza compilata disponibile")
        export_data = self._latest_compiled
        assumptions_report = self.state.assumptions_report or "Nessuna assunzione applicata."

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        INSTANCE_PATH.write_text(json.dumps(export_data, indent=2), encoding="utf-8")
        ASSUMPTIONS_PATH.write_text(assumptions_report, encoding="utf-8")

        logger.info("Istanza esportata in %s", INSTANCE_PATH)
        self._export_done = True
        self._export_waiting = False
        self.state.export_completed = True

        message_lines = [
            "Ho salvato l'istanza in out/instance.json e il report delle assunzioni in out/assumptions.txt.",
        ]
        if self._latest_summary_hint:
            message_lines.append(self._latest_summary_hint)
        message_lines.append("Assunzioni principali:")
        for line in assumptions_report.splitlines()[:5]:
            message_lines.append(f"- {line}")
        message_lines.append("Conversazione chiusa: puoi tornare al menu o avviare l'ottimizzazione.")
        return "\n".join(message_lines)

    def _compose_summary_hint(self, compiled: Dict[str, Any]) -> str:
        slots = int(compiled.get("time", {}).get("slots", 0))
        activities = len(compiled.get("activities", []))
        machines = len(compiled.get("machines", []))
        objective = compiled.get("objective", "min_cost")
        hours = slots * (5 / 60) if slots else 0
        suffix = ""
        report = self.state.assumptions_report or ""
        if "default 1 persona" in report.lower():
            suffix = " (workforce default)"
        return f"Riepilogo: obiettivo {objective}, {activities} attivita, {machines} macchine, orizzonte ~{hours:.1f} ore{suffix}."

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _seed_history(self) -> None:
        self.state.messages.append({"role": "system", "content": self._system_prompt})
        self.state.messages.extend(self._few_shot_messages)

    def _prepare_few_shots(self, examples: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        for example in examples:
            user = example.get("user", "")
            assistant = example.get("assistant", "")
            save_block = example.get("save_block", "")
            parts: List[str] = []
            if user:
                parts.append(f"Esempio utente:\n{user}")
            if assistant:
                assistant_payload = assistant if not save_block else f"{assistant}\n{save_block}"
                parts.append(f"Esempio assistente:\n{assistant_payload}")
            if parts:
                messages.append({"role": "system", "content": "\n".join(parts)})
        return messages


    def _retry_save_blocks(self, original_reply: str) -> bool:
        for attempt in range(2):
            if self._log_prompts:
                logger.debug("Richiedo ri-emissione del blocco SAVE (tentativo %s)", attempt + 1)
            self.state.messages.append({"role": "assistant", "content": original_reply})
            self.state.messages.append({"role": "system", "content": self._reemit_save_prompt})
            raw_retry = self._call_provider()
            retry_response = sanitize_llm_output(raw_retry, max(self._turn_index, 1))
            self.state.messages.append({"role": "assistant", "content": retry_response})
            retry_extraction = extract_save_blocks(retry_response)
            if retry_extraction.errors:
                logger.warning("Ri-emissione SAVE non valida: %s", [e.message for e in retry_extraction.errors])
                continue
            for block in retry_extraction.blocks:
                self.store.ingest(block.triples)
                self._last_save_block = block.raw_json
            self._update_flags()
            return True
        logger.error("Ri-emissione SAVE fallita dopo 2 tentativi.")
        return False

    def last_save_snapshot(self) -> Optional[str]:
        """Restituisce l'ultimo blocco SAVE registrato."""
        return self._last_save_block

__all__ = ["ConversationConfig", "ConversationState", "Orchestrator"]


