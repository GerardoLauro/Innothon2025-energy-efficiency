> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Architecture Overview

## Flusso principale
1. CLI (`energy_planner.cli.app`): carica le variabili da `.env`, risolve il provider LLM tramite `provider_from_env_or_args` e avvia il comando `chat`.
2. Orchestratore (`energy_planner.nlu.orchestrator.Orchestrator`): governa la sessione CLI, mantiene lo stato della conversazione e decide quando proporre il riepilogo o l'export.
3. Estrattore SAVE (`energy_planner.nlu.save_extractor.extract_save_blocks`): individua i blocchi `>>> SAVE`, li valida come array JSON e li trasforma in `Triple`.
4. TripleStore (`energy_planner.core.triple_store.TripleStore`): deduplica e archivia le triplette, offrendo query filtrate per prefisso o relazione.
5. Normalizzazione (`energy_planner.core.normalization.normalize_context`): produce serie di prezzo e workforce su slot da 5 minuti, applicando fallback (flat 0.25 EUR/kWh, workforce 1 persona/slot) e annotando le assunzioni applicate.
6. Compilatore (`energy_planner.core.compiler.compile_instance`): combina triplette e contesto normalizzato in un dizionario conforme allo schema di istanza (time, pricing, workforce, machines, activities, objective, locks, assumptions).
7. Validazione (`energy_planner.core.validation.validate`): controlla finestre, precedenze, workforce, macchine e limiti di potenza restituendo `ValidationIssue` con severity e suggerimenti.
8. Modulo prezzi (`energy_planner.price.loader`): carica serie orarie da `data/prices/<citta>.json`, interpreta valori incollati dall'utente e li upsample agli slot.
9. Report assunzioni (`energy_planner.reports.assumptions`): combina le assunzioni accumulate, aggiunge fallback standard e genera il testo per `out/assumptions.txt`.
10. Export finale (`Orchestrator._perform_export`): dopo conferma dell'utente scrive `out/instance.json` e `out/assumptions.txt`, segnala i percorsi e marca l'export come completato.

## Interfacce fra moduli
- CLI -> Orchestratore: turni utente e flag (`--provider`, `--model`, `--stream`, `--export-auto`, ecc.).
- Orchestratore -> Estrattore SAVE: testo completo del modello contenente i blocchi `>>> SAVE`.
- Estrattore -> TripleStore: liste di `Triple` validate e deduplicate.
- TripleStore -> Compilatore: snapshot coerente delle triplette correnti.
- Compilatore -> Normalizzazione/Validazione: dati strutturati su slot, workforce, macchine, attivita' e vincoli.
- Normalizzazione -> Report: elenco delle assunzioni generate dai fallback di prezzo/workforce.
- Validazione -> CLI: `ValidationIssue` mostrati come avvisi all'utente.
- Modulo prezzi -> Compilatore: vettori `pricing` coerenti con l'orizzonte temporale.
- Export -> File system: aggiornamento di `out/instance.json` e `out/assumptions.txt`.

## Estensibilita
- Nuove citta: aggiungere file JSON in `data/prices/` o estendere `load_city_hourly` con adapter verso servizi esterni.
- Nuovi provider LLM: implementare `LLMProvider` e registrarli dentro `provider_from_env_or_args`.
- Regole aggiuntive: ampliare `energy_planner.core.normalization` o `energy_planner.core.validation` mantenendo la firma di `ValidationInput`/`ValidationIssue`.
- Scheduler futuri: consumano `out/instance.json`; collocare l'integrazione in `optimization/` o nei moduli `energy_planner.scheduler`.
