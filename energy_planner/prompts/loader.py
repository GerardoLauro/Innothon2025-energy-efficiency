"""Caricamento dei prompt di sistema e degli esempi few-shot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
import re
import json

PROMPTS_SUBDIR = Path(__file__).resolve().parent
SYSTEM_FILENAME = "system_orchestrator.txt"
FEW_SHOTS_FILENAME = "few_shots.md"
REEMIT_SAVE_FILENAME = "reemit_save_strict.txt"


class PromptNotFoundError(FileNotFoundError):
    """Errore sollevato quando un file di prompt non e disponibile."""


def _resolve_prompt_path(path_or_env: str | Path | None, filename: str) -> Path:
    """Determina il percorso del file di prompt considerando input espliciti e PROMPTS_DIR."""
    candidates: Iterable[Path]
    if path_or_env:
        base = Path(path_or_env)
        candidates = (base / filename,) if base.is_dir() else (base,)
    else:
        env_dir = os.environ.get("PROMPTS_DIR")
        if env_dir:
            base = Path(env_dir)
            candidates = (base / filename,) if base.is_dir() else (base,)
        else:
            candidates = (PROMPTS_SUBDIR / filename,)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    raise PromptNotFoundError(
        f"Impossibile trovare il file di prompt '{filename}'. "
        "Verifica la variabile PROMPTS_DIR o specifica un percorso valido."
    )


def load_system_prompt(path_or_env: str | Path | None = None) -> str:
    """Restituisce il system prompt (supporto path di default e custom)."""
    path = _resolve_prompt_path(path_or_env, SYSTEM_FILENAME)
    text = path.read_text(encoding="utf-8-sig")  # rimuove BOM se presente
    return text.replace("\r\n", "\n").replace("\r", "\n")  # normalizza newline


def load_few_shots(path_or_env: str | Path | None = None) -> list[dict[str, str]]:
    """Carica gli esempi few-shot, restituendo una lista con titolo, utente, assistente e blocco SAVE."""
    path = _resolve_prompt_path(path_or_env, FEW_SHOTS_FILENAME)
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return _parse_few_shots(raw, path)


def load_reemit_save_prompt(path_or_env: str | Path | None = None) -> str:
    """Restituisce il prompt da usare quando il blocco SAVE risulta invalido."""
    path = _resolve_prompt_path(path_or_env, REEMIT_SAVE_FILENAME)
    text = path.read_text(encoding="utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse_few_shots(raw: str, origin: Path) -> list[dict[str, str]]:
    """Converte il Markdown few-shot in una lista di esempi strutturati.

    Tollerante a:
    - intestazioni con o senza ":" e varianti (Messaggio Utente/Utente/User, Risposta Assistente/Assistente/Assistant)
    - code-fence ``` (anche ```json)
    - CRLF/UTF-8 BOM
    - righe vuote e separatori '---'

    Richiede comunque:
    - almeno una riga che inizi con ">>> SAVE"
    - un array JSON valido tra la prima '[' e la ']' corrispondente
    """

    def split_sections(md: str) -> list[str]:
        """Raccoglie SOLO le sezioni che iniziano con '### ' (salta il preambolo tipo '# ...')."""
        sections: list[str] = []
        for m in re.finditer(r'(?m)^\s*###\s+(.*)$', md):
            start = m.start()
            # fine = inizio della prossima sezione '###' o fine file
            next_m = re.search(r'(?m)^\s*###\s+.*$', md[m.end():])
            end = (m.end() + next_m.start()) if next_m else len(md)
            block = md[start:end].strip()
            sections.append(block)
        return [s for s in sections if s]

    def find_header(body: str, labels: list[str]) -> re.Match | None:
        # **Messaggio Utente:** / **Utente:** / **User** (case-insensitive; ":" opzionale)
        pattern = r'(?mi)^\s*\*\*\s*(?:' + "|".join(labels) + r')\s*:?\s*\*\*\s*(.*)$'
        return re.search(pattern, body)

    def strip_code_fence(s: str) -> str:
        s = s.strip()
        s = re.sub(r'(?is)^```(?:json)?\s*', '', s)
        s = re.sub(r'(?is)```$', '', s)
        return s.strip()

    def take_until_next_header_or_save(text: str) -> str:
        m = re.search(r'(?m)^\s*(?:\*\*.+\*\*|>>>[ ]*SAVE)', text)
        end = m.start() if m else len(text)
        return text[:end].strip()

    def extract_save_array(save_block_text: str, section_title: str) -> str:
        """Dal testo successivo a '>>> SAVE' estrae l'array JSON (bilanciando []), valida con json.loads."""
        text = strip_code_fence(save_block_text)
        i = text.find('[')
        if i == -1:
            raise ValueError(f"In '{origin}' → sezione '{section_title}': dopo >>> SAVE non trovo '['.")
        balance = 0
        end_idx = None
        for j, ch in enumerate(text[i:], start=i):
            if ch == '[':
                balance += 1
            elif ch == ']':
                balance -= 1
                if balance == 0:
                    end_idx = j
                    break
        if end_idx is None:
            raise ValueError(f"In '{origin}' → sezione '{section_title}': array JSON non chiuso con ']'.")
        arr = text[i:end_idx + 1].strip()
        try:
            json.loads(arr)
        except Exception as e:
            raise ValueError(
                f"In '{origin}' → sezione '{section_title}': blocco >>> SAVE non è JSON valido. Dettaglio: {e}"
            )
        return arr

    sections = split_sections(raw)
    if not sections:
        raise ValueError(
            f"Formato few-shot non valido in '{origin}': nessuna sezione '###' trovata."
        )

    entries: list[dict[str, str]] = []
    for idx, section in enumerate(sections, start=1):
        lines = [ln for ln in section.splitlines() if ln.strip()]
        if not lines:
            continue

        # la prima riga della sezione è "### Titolo ..."
        title_line = lines[0].lstrip('#').strip()
        # il corpo della sezione è tutto ciò che segue
        body = "\n".join(lines[1:])

        # pulizia separatori '---'
        body = re.sub(r'(?m)^\s*---\s*$', '', body)

        # Trova intestazioni utente/assistente (accetta varianti)
        m_user = find_header(body, ["messaggio\\s+utente", "utente", "user"])
        m_ass = find_header(body, ["risposta\\s+assistente", "assistente", "assistant"])

        if not m_user or not m_ass:
            raise ValueError(
                f"Formato few-shot non valido in '{origin}': manca Messaggio Utente o Risposta Assistente "
                f"nella sezione {idx} ('{title_line}')."
            )

        # Testo inline dopo le intestazioni (stessa riga) se presente
        user_inline = (m_user.group(1) or "").strip()
        ass_inline = (m_ass.group(1) or "").strip()

        # Testo utente: inline oppure blocco fino alla prossima intestazione/>>> SAVE
        tail_after_user = body[m_user.end():]
        user_block = take_until_next_header_or_save(tail_after_user)
        user_text = user_inline if user_inline else user_block

        # Dalla fine dell'intestazione assistente fino a >>> SAVE
        tail_after_ass = body[m_ass.end():]
        m_save = re.search(r'(?mi)^\s*>>>[ ]*SAVE\b.*$', tail_after_ass)
        if not m_save:
            raise ValueError(
                f"Formato few-shot non valido in '{origin}': manca il blocco >>> SAVE nella sezione {idx} ('{title_line}')."
            )
        assistant_block = tail_after_ass[:m_save.start()].strip()
        assistant_text = ass_inline if ass_inline else assistant_block

        save_body = tail_after_ass[m_save.end():].strip()
        save_json = extract_save_array(save_body, title_line)

        entries.append(
            {
                "title": title_line,
                "user": user_text,
                "assistant": assistant_text,
                "save_block": ">>> SAVE\n" + save_json,
            }
        )

    return entries


__all__ = [
    "PromptNotFoundError",
    "load_system_prompt",
    "load_few_shots",
    "load_reemit_save_prompt",
]
