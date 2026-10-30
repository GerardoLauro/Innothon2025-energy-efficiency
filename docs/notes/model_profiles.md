> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Model Profiles

## Local-Small (7B–8B)
- Limita la conversazione a una domanda per turno; evita frasi complesse.
- Imposta la temperatura tra 0.0 e 0.2 per massima stabilita del JSON.
- Applica sempre il flusso SAVE-STRICT e mantieni `retry=2` per blocchi non validi.
- Preferisci prompt sintetici e coerenti; niente divagazioni o esempi lunghi.

## Local-Medium (12B–14B)
- Permetti fino a due domande per turno mantenendo indicazioni concise.
- Temperature consigliate 0.1–0.3 con top_p 1.0 per bilanciare stabilita e flessibilita.
- Continua a usare SAVE-STRICT per i blocchi di persistenza; riusa i dati senza reinterpretarli.
- Ricorda di confermare sempre i campi cruciali prima di forzare un salvataggio.

## API-Pro (servizi gestiti)
- Fino a due domande per turno con contesto strutturato.
- Temperature 0.1–0.3 e top_p 1.0; abilita lo streaming per feedback immediato.
- Applica SAVE-STRICT e considera `--no-log-prompt` per minimizzare la persistenza di dati sensibili.
- Sfrutta le metriche di latenza e quota del provider per tarare backoff e timeout.
