> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Visione

- Assistente conversazionale che raccoglie requisiti aziendali per lo scheduling energetico (slot da 5') e produce un JSON di istanza schedulabile.
- Selezione della citta' (Milano, Roma, Napoli) per usare previsioni di prezzo orarie da modulo interno/esterno.
- Riconoscimento dell'offerta Enel (Fix/monoraria, Flex indicizzata PUN, PLACET fissa/variabile) per impostare l'obiettivo primario (`min_cost` o `min_peak`).
- LLM orchestratore + parser deterministico (`>>> SAVE` -> normalizzatore -> validatore -> compilatore JSON).
- Scelta del modello LLM via CLI/env: Ollama locale oppure provider API con chiave dedicata.
