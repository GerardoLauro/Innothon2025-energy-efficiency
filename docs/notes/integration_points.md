> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Integration Points

## Modulo prezzi
- Input atteso: serie orarie (24 valori) per citta' supportate (Milano, Roma, Napoli) salvate in `data/prices/<citta>.json` o incollate via CLI.
- `energy_planner.price.loader.load_city_hourly` legge i file locali, `parse_user_hourly_series` interpreta incolli liberi e `upsample_hourly_to_slots` replica sui 5 minuti.
- Integrazione futura: aggiungere adapter per forecast esterni e aggiornare automaticamente il `TripleStore` con `["price","per_hour",...]`.

## Scheduler / euristiche
- Output principale: `out/instance.json` prodotto da `compile_instance`, coerente con `spec/instance_schema.md`.
- I solver in `optimization/` o `energy_planner.scheduler` potranno consumare l'istanza, restituire uno schedule e scrivere report aggiuntivi.

## Interfaccia UI
- Una UI desktop/web puo' riutilizzare orchestratore, provider LLM e prompt caricati da `prompts/`.
- Gli eventi utente devono essere tradotti in turni della chat, visualizzando i blocchi `>>> SAVE` in formato JSON puro.
- Requisito futuro: supportare scenari multi-utente e la persistenza delle triplette su storage condiviso.

## Versioning dello schema
- Ogni modifica allo schema di istanza richiede un incremento versione (`instance.version`).
- Le utility di migrazione devono aggiornare file legacy e documentare gli impatti in `spec/instance_schema.md` e `docs/errors_and_logs.md`.
- Notificare i consumer (solver, UI, integrazioni esterne) di ogni breaking change.
