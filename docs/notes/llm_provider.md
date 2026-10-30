> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# LLM Provider Configuration

## Modalita' supportate
- `ollama`: usa un modello locale esposto da `ollama serve`.
- `api`: invia richieste a un servizio esterno tramite API key.
- `mock`: placeholder per test deterministici (attualmente solleva `NotImplementedError`).

## Parametri configurabili
Impostabili via `.env` o flag CLI:

- `LLM_PROVIDER` = `ollama` | `api` | `mock`
- `OLLAMA_HOST`: URL del demone (es. `http://127.0.0.1:11434`)
- `OLLAMA_MODEL`: modello da interrogare (default `llama3.1:8b`)
- `API_BASE_URL`: endpoint REST del provider (`https://...`)
- `API_KEY`: token di autenticazione
- `API_MODEL`: identificatore del modello remoto
- `PROMPTS_DIR`: percorso dei prompt (default `./prompts`)

I parametri di generazione (`--temperature`, `--top-p`, `--max-tokens`, `--timeout`) vengono inoltrati a `provider_from_env_or_args` e applicati al provider selezionato.

## Regole comuni di utilizzo
- Abilita `--stream` per risposte token-by-token se il provider lo supporta.
- Mantieni `temperature` bassa (0.0-0.3) per ridurre errori nel JSON strutturato.
- `--no-log-prompt` evita che i contenuti della chat vengano registrati nei log.
- Per Ollama assicurati di avere eseguito `ollama pull <modello>` prima dell'uso.
- Per provider API monitora latenza, retry e rate limit: il client gestisce `HTTP 429` con backoff ma richiede parametri coerenti (`API_BASE_URL`, `API_KEY`, `API_MODEL`).

## Testing di piu' modelli
1. Aggiorna `.env` con il provider desiderato oppure passa i flag CLI.
2. Esegui `python -m energy_planner.cli.app chat --provider ... --model ...` per avviare una sessione.
3. Con Ollama e' sufficiente cambiare `OLLAMA_MODEL`; host e prompt restano invariati.
4. Con provider API modifica `API_MODEL` (e, se necessario, `API_BASE_URL`).
5. Usa `python -m energy_planner.cli.app config show` per verificare la sorgente attuale dei parametri.
