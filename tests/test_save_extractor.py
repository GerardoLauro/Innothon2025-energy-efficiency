import logging

import pytest

from energy_planner.nlu.save_extractor import extract_save_blocks


def test_save_block_with_pipe_is_ignored():
    text = "Risposta...\n>>> SAVE | [[\"machine:press1\", \"relation\", \"value\"]]"

    result = extract_save_blocks(text)

    assert result.blocks == []
    assert len(result.errors) == 1
    assert "JSON non trovato o non valido" in result.errors[0].message


def test_save_block_with_trailing_text_is_parsed():
    text = ">>> SAVE\n[[\"machine:press1\", \"relation\", 1]] trailing note"

    result = extract_save_blocks(text)

    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert block.triples[0].subject == "machine:press1"
    assert block.triples[0].relation == "relation"
    assert block.triples[0].value == 1
    assert block.raw_json == '[[\"machine:press1\", \"relation\", 1]]'
    assert result.errors == []


def test_save_block_inside_code_fence():
    text = """>>> SAVE
```json
[
  ["machine:press1", "relation", "value"]
]
```
"""

    result = extract_save_blocks(text)

    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert block.triples[0].subject == "machine:press1"
    assert block.triples[0].relation == "relation"
    assert block.triples[0].value == "value"
    assert result.errors == []


def test_save_block_object_is_coerced_to_array(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="energy_planner.nlu.save_extractor")
    text = """>>> SAVE
{"subject": "machine:press1", "relation": "relation", "value": 1}
"""

    result = extract_save_blocks(text)

    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert block.triples[0].subject == "machine:press1"
    assert block.triples[0].relation == "relation"
    assert block.triples[0].value == 1
    assert any("Payload SAVE era un oggetto JSON" in record.message for record in caplog.records)
