> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# CLI Usage Guide

## Quickstart
1. Configura `.env` indicando:
   - `LLM_PROVIDER=ollama` (oppure `api` se usi un servizio cloud)
   - `OLLAMA_MODEL=llama3.1:8b` oppure `API_MODEL=gpt-4o-mini`
   - `PROMPTS_DIR=./prompts`
2. Avvia la chat con `python -m energy_planner.cli.app chat` (`--export-auto` per export automatico, `--debug` per mostrare i blocchi `SAVE`).
3. Sequenza tipica di 5-7 turni:
   - l'assistente chiede citta', offerta, potenza contrattuale
   - se i prezzi non esistono propone (A) incolla i 24 valori EUR/kWh, (B) usa la serie flat 0.25 SIMULAZIONE
   - l'utente definisce workforce, attivita' e conferma assunzioni
4. Quando i dati minimi sono completi l'assistente mostra il riepilogo e chiede "Posso esportare ora?".
5. Conferma (anche input vuoto se `--export-auto`): vengono emessi `out/instance.json` e `out/assumptions.txt`, poi puoi continuare o terminare.

## Turni di esempio
1. Operatore: avvia la chat (`--provider ollama`). Assistente chiede citta', offerta, potenza.
2. Operatore: "Milano, Flex indicizzata, nessuna potenza dichiarata" -> assistente salva citta', obiettivo `min_cost`.
3. Operatore: "Uso serie flat di test" -> assistente registra prezzi flat 0.25 SIMULAZIONE.
4. Operatore: "Workforce default per ora" -> assistente applica fallback 1 persona/slot.
5. Operatore: descrive attivita' (durata, finestra, macchina) -> assistente allinea agli slot e salva `>>> SAVE`.
6. Assistente: rileva readiness, mostra riepilogo, chiede conferma export.
7. Operatore: conferma; l'assistente salva `out/instance.json` e `out/assumptions.txt`, mostra i percorsi e chiede se proseguire.

## Troubleshooting rapido
| Problema | Cosa fare |
| --- | --- |
| Demone Ollama non raggiungibile | Avvia `ollama serve`, esegui `ollama pull <modello>`, verifica `OLLAMA_HOST` |
| API key mancante | Popola `API_BASE_URL`, `API_KEY`, `API_MODEL` in `.env` o passa `--api-base-url`, `--api-key`, `--model` |
| Prezzi assenti | Usa `python -m energy_planner.cli.app prices paste --city <citta>` oppure scegli la serie flat quando richiesto |
| Blocco `>>> SAVE` invalido | Ri-emetti solo un array JSON (nessun `|` o testo extra). Con `--debug` puoi digitare `show save` per rivedere l'ultimo blocco |
| Precedenze cicliche | Rimuovi o modifica le dipendenze; l'assistente segnala l'anomalia |

> Nota: se un blocco `>>> SAVE` non e' JSON valido, l'assistente chiede di ripetere il blocco. Con il flag `--debug` puoi usare il comando `show save` per ristampare l'ultimo salvataggio.
