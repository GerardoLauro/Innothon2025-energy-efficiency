> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# LLM Configuration Flow

## Ordine di precedenza
Il caricamento delle impostazioni LLM segue (1) flag CLI, (2) variabili `.env`/ambiente, (3) default in `energy_planner.cli.app`:

1. **Flag CLI** - `python -m energy_planner.cli.app chat --provider ... --model ... --api-base-url ... --api-key ...`.
2. **Variabili di ambiente** - `LLM_PROVIDER`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `API_BASE_URL`, `API_KEY`, `API_MODEL` caricate tramite `python-dotenv`.
3. **Default applicativi** - quando CLI e ambiente non forniscono valori vengono usati `DEFAULT_PROVIDER=ollama`, `DEFAULT_OLLAMA_MODEL=llama3.1:8b`, `DEFAULT_PROMPTS_DIR=./prompts`, `DEFAULT_OLLAMA_HOST=http://127.0.0.1:11434`.

## Visualizzare la configurazione
`python -m energy_planner.cli.app config show` stampa valore e origine. Le chiavi sensibili sono mascherate.

```
$ python -m energy_planner.cli.app config show
Configurazione corrente (valore [origine]):
- Provider: api [.env (LLM_PROVIDER)]
  -> Provider effettivo: api/gpt-4o
- API base URL: https://api.openai.com/v1 [.env (API_BASE_URL)]
- Modello API: gpt-4o-mini [.env (API_MODEL)]
- API key: ***1234 [.env (API_KEY)]
- Prompt directory: ./prompts [default]
```

Aggiungi `--provider`, `--model`, `--api-base-url`, `--api-key`, `--ollama-host`, `--prompts-dir` al comando per simulare override temporanei.

## Streaming e parametri di generazione
- `--stream` abilita la risposta token-by-token (non esiste variabile `LLM_STREAM`).
- Con `provider=api` la CLI imposta di default `temperature=0.1` e `top_p=1.0` quando costruisce il provider.
- Per variare temperature, top_p, max_tokens o timeout e' necessario estendere `provider_from_env_or_args` o aggiungere nuovi flag CLI (non ancora esposti).
- In modalita' Ollama i parametri restano `None` e vengono usati i default del demone.

## Suggerimenti operativi
- Mantieni `.env` minimal e usa i flag per cambiare rapidamente provider e modello.
- `--no-log-prompt` evita che i contenuti della chat vengano registrati quando gestisci dati sensibili.
- Per test senza LLM reale puoi impostare `LLM_PROVIDER=mock`, sapendo che `MockProvider` e' ancora un placeholder e sollevera' `NotImplementedError` finche' non vengono caricate risposte fittizie.
