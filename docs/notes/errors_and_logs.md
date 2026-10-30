> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Errori e Logging

## Tabelle errori comuni

| Errore | Causa probabile | Come risolvere |
| --- | --- | --- |
| Impossibile raggiungere Ollama | Il demone `ollama serve` non e' attivo o il modello manca | Avvia `ollama serve`, esegui `ollama pull <modello>`, verifica `OLLAMA_HOST` |
| Configurazione API incompleta | Variabili `API_BASE_URL`, `API_KEY`, `API_MODEL` mancanti | Imposta le variabili in `.env` o passa `--api-base-url`, `--api-key`, `--model` |
| Prezzi non disponibili per la citta' | File `data/prices/<citta>.json` assente o con meno di 24 valori | Usa `python -m energy_planner.cli.app prices paste --city ...` o applica la serie flat |
| Blocco `>>> SAVE` non valido | JSON malformato o triplette fuori schema | Correggi il blocco secondo la tassonomia (array di 3-4 elementi). `save_extractor` logga il motivo |
| Precedenze cicliche | Attivita' che si rimandano a vicenda | Rimuovi/aggiusta la dipendenza; il validatore segnala il ciclo |

## Livelli di logging consigliati

| Ambiente | Livello | Note |
| --- | --- | --- |
| Sviluppo | DEBUG | Traccia fallback, parsing `save_extractor` e messaggi dell'orchestratore |
| Produzione | INFO | Mostra tappe principali; WARN/ERROR per anomalie |
| Test automatici | WARNING | Mantiene l'output pulito; usare `--debug` solo per investigazioni puntuali |

Per configurare il logging, imposta `LOG_LEVEL` oppure richiama `logging.basicConfig` prima di avviare `python -m energy_planner.cli.app chat`. Con `--debug` la CLI forza `logging.DEBUG` e abilita il comando `show save`.

## Gestione dei blocchi SAVE non validi
- `energy_planner.nlu.save_extractor.extract_save_blocks` restituisce `SaveExtractionResult` con `errors`; ogni errore include contesto e posizione.
- L'orchestratore invia `RE-EMIT SAVE STRICT` al modello e tenta fino a due volte di rigenerare il blocco.
- Se il blocco resta invalido, il flusso continua ma l'utente viene informato che il salvataggio e' stato ignorato.
- In modalita' streaming i token vengono bufferizzati finche' non viene chiusa `]`; se la risposta e' troncata il parser attende la continuazione e logga `DEBUG`.

## Note per Windows
- Apri PowerShell nella cartella del progetto e duplica `.env.example` in `.env` prima di lanciare la CLI.
- Se compare l'avviso "Attenzione: file .env non trovato", crea il file e rilancia il comando; le variabili caricate valgono solo nella sessione corrente.
- Per verificare le variabili caricate usa `Get-ChildItem Env: | Select-String LLM_` oppure `python -m dotenv list` dalla stessa cartella.
