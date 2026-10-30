from energy_planner.nlu.orchestrator import (
    sanitize_llm_output,
    extract_save_json,
    _looks_incomplete,
)
from energy_planner.nlu.save_extractor import _canonicalize_triple_subject
from energy_planner.prompts.loader import load_few_shots


def test_sanitize_first_turn_no_save():
    raw_text = "<think>internal reasoning</think> >>> SAVE\n[[\"price\",\"city\",\"Milano\"]]"

    cleaned = sanitize_llm_output(raw_text, turn_idx=0)

    assert ">>> SAVE" not in cleaned
    assert "<think>" not in cleaned.lower()


def test_extract_and_filter_incomplete_triples():
    text = (
        ">>> SAVE\n"
        "["
        '["activity:Impasto","duration_min",0],'
        '["activity:Cottura","duration_min",30]'
        "]"
    )

    triples = extract_save_json(text)
    assert triples is not None

    filtered = [
        triple
        for triple in triples
        if isinstance(triple, list) and not _looks_incomplete(triple)
    ]

    assert filtered == [["activity:Cottura", "duration_min", 30]]


def test_alias_subjects():
    inputs = [
        ["city", "name", "Milano"],
        ["offer", "type", "ENEL_X"],
        ["contract_power_kW", "value", 30],
    ]

    outputs = [_canonicalize_triple_subject(triple) for triple in inputs]

    assert outputs == [
        ["price", "city", "Milano"],
        ["note", "assumption", "Offerta ENEL_X"],
        ["note", "assumption", "Potenza contrattuale 30 kW"],
    ]


def test_loader_fewshots_flexible_headers():
    few_shots = load_few_shots()

    assert few_shots, "Il loader deve restituire almeno un few-shot"
    for entry in few_shots:
        assert "user" in entry
        assert "assistant" in entry
        save_block = entry.get("save_block") or ""
        if ">>> SAVE" in save_block:
            payload_start = save_block.find(">>> SAVE")
            array_part = save_block[payload_start + len(">>> SAVE") :].strip()
            assert array_part.startswith("[")
            assert array_part.endswith("]")
