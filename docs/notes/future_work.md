> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Future Work

## Integrazione solver
- Implementare una pipeline euristica (greedy iniziale + local search) per produrre uno schedule fattibile a partire da `out/instance.json`.
- Progettare un modello MIP con solver open-source (es. CBC) come baseline, con possibilita' di integrare Gurobi/CPLEX per casi avanzati.
- Definire interfacce stabili tra compilatore e solver includendo warm-start e parametri di ottimizzazione.

## UI grafica
- Disegnare una dashboard web che replichi il workflow CLI con un wizard conversazionale.
- Prevedere viste per attivita', assunzioni e configurazione del provider LLM.
- Pianificare l'integrazione con componenti front-end senza rallentare la CLI.

## Logging e metriche
- Introdurre logging strutturato per domande, blocchi `>>> SAVE` e correzioni.
- Definire metriche di qualita' conversazionale (tasso di conferme, richieste di chiarimento) per iterare sui prompt.
- Analizzare i log per suggerire aggiornamenti alla knowledge base e ai few-shot.

## Versioning dello schema JSON
- Assegnare un numero di versione al JSON di istanza e riportarlo in `out/assumptions.txt`/`out/instance.json`.
- Documentare procedure di migrazione quando cambiano campi o semantica.
- Fornire tool di validazione/upgrade per convertire istanze legacy allo schema corrente.
