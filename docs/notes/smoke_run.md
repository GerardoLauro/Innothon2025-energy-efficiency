> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Smoke Run Senza LLM

Questo scenario mostra come testare la CLI senza contattare provider esterni. Attenzione: `MockProvider` attualmente solleva `NotImplementedError`; serve predisporre risposte fittizie prima di usarlo in CI.

## Prerequisiti
- File `.env` con `LLM_PROVIDER=mock` (oppure passare `--provider mock`).
- Prompt/few-shot aggiornati nelle cartelle `prompts/`.
- Nessuna dipendenza da GPU o demone Ollama.

## Esecuzione rapida
1. Duplica `.env.example` in `.env` e imposta:
   ```ini
   LLM_PROVIDER=mock
   ```
2. Avvia:
   ```powershell
   python -m energy_planner.cli.app chat --provider mock --prompts-dir ./prompts
   ```
3. Al primo completamento il codice lancia `NotImplementedError` finche' non vengono fornite risposte mock (TODO futuro). Usa il comando per verificare che il wiring CLI e il caricamento `.env` funzionino.

## Integrazione in CI
- Predisponi una fixture che monkeypatcha `MockProvider.complete` restituendo risposte deterministiche prima di lanciare i test.
- Esegui `pytest -k smoke` o script equivalenti per validare parsing `>>> SAVE`, persistenza `out/`, fallback prezzi/workforce.
- Ripristina il comportamento originale dopo i test per evitare side-effect.

> Nota: quando il provider mock verra' completato, aggiorna questa guida includendo esempi di output attesi.
