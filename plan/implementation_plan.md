# Implementation Plan

## Moduli da implementare
- `nlu/orchestrator`: gestisce i turni di conversazione, carica system prompt e few-shots, invoca il provider LLM e coordina la produzione dei blocchi `>>> SAVE`.
- `io/save_block_extractor`: effettua il parsing robusto dei blocchi `>>> SAVE`, separando le triplette dal testo libero e validandone la sintassi.
- `core/triple_store`: mantiene la memoria delle triplette normalizzate, supportando versionamento leggero, query per soggetto e tracciamento delle assunzioni.
- `core/normalizer`: applica lo snap a 5 minuti, converte range vaghi, trasforma workforce in vettori `E_l` e prezzi orari in serie per slot.
- `core/validator`: verifica vincoli temporali, precedenze acicliche, capacità workforce/macchine e coerenza delle potenze.
- `core/compiler`: costruisce il JSON di istanza schedulabile e il report associato partendo dal triple store validato.
- `core/tariffs`: classifica le offerte commerciali e determina l’obiettivo (`min_cost` o `min_peak`) e gli eventuali vincoli di picco.
- `price/loader`: carica le previsioni per città, applica l’upsample e gestisce i fallback quando i dati mancano.
- `llm/provider`: incapsula l’accesso ai modelli Ollama/locali e ai provider API remoti, includendo lo streaming.
- `cli/app`: offre l’interfaccia a riga di comando per avviare la chat, impostare flag, gestire lo streaming e l’esportazione dei risultati.
- `reports/assumptions`: genera il riepilogo delle assunzioni attive e delle sostituzioni effettuate durante la sessione.

## Dipendenze e ordine suggerito
1. `core/tariffs` e `price/loader`: necessari per impostare obiettivi e prezzi base.
2. `llm/provider`: garantisce la disponibilità del modello per i test manuali.
3. `nlu/orchestrator` e `io/save_block_extractor`: permettono di orchestrare un flusso completo di triplette.
4. `core/triple_store`: fondamentale per persistere i dati estratti.
5. `core/normalizer` ? `core/validator`: normalizzazione e validazione vanno implementate in sequenza per garantire input puliti.
6. `core/compiler`: dipende da triple store, normalizzatore, validatore e price loader.
7. `reports/assumptions`: richiede triple store e normalizzatore per elencare le assunzioni.
8. `cli/app`: si appoggia a tutti i moduli precedenti per esporre la funzionalità end-to-end.

## Criteri di completamento
- `core/tariffs`: dati in ingresso (stringhe da utente) classificati correttamente in oltre il 95% di test; output include obiettivo e vincoli derivati.
- `price/loader`: verifica che 24 valori producano H slot coerenti; fallback registrato quando i dati mancano.
- `llm/provider`: deve sostenere richieste sincrone e streaming, con tempi di timeout configurabili e messaggi di errore user-friendly.
- `nlu/orchestrator`: gestisce turni con massimo due domande, applica il system prompt e invia conferme `>>> SAVE` valide.
- `io/save_block_extractor`: riconosce blocchi anche con spazi o testo extra, invalidando formati errati e restituendo errori chiari.
- `core/triple_store`: supporta inserimento, aggiornamento con `superseded_by`, query per soggetto e generazione di snapshot coerenti.
- `core/normalizer`: dimostra, tramite test, che orari/durate vengono allineati a 5 minuti e che workforce/prezzi sono trasformati correttamente.
- `core/validator`: evidenzia cicli, violazioni di capacità e finestre inconsistenti, bloccando la compilazione quando necessario.
- `core/compiler`: produce un JSON conforme allo schema definito e un report di assunzioni, entrambi validati in test end-to-end.
- `reports/assumptions`: elenca assunzioni attive, risolte e note di warning con riferimenti alle triplette origine.
- `cli/app`: scenario end-to-end (già descritto) deve concludersi con export riuscito e nessun errore non gestito.
