# Innothon2025 - Energy Planner

Prototipo Python per raccogliere requisiti energetici tramite chat, compilare
un'istanza JSON, calcolare uno scheduling e generare un report.

Il progetto comprende una CLI, un ottimizzatore PuLP/CBC con fallback euristico
e un modulo di forecasting opzionale. La demo usa dati sintetici e non richiede
chiavi API, Ollama, dati originali o addestramento di modelli.

## Requisiti

- Python **3.12 o successivo**. Ambiente verificato localmente: Python 3.12 su Windows.
- Per la chat: Ollama configurato localmente oppure un provider API compatibile.
- Le dipendenze opzionali di forecasting e ricerca si installano separatamente.
- L'applicazione non installa librerie e non scarica solutori durante l'avvio.

## Installazione

Aprire un terminale nella radice del progetto.

**Windows PowerShell**:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-base.lock
.\.venv\Scripts\python.exe -m pip install --no-deps .
.\.venv\Scripts\python.exe -m energy_planner demo
```

**Linux / macOS**:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-base.lock
.venv/bin/python -m pip install --no-deps .
.venv/bin/python -m energy_planner demo
```

In alternativa usare `scripts/setup.ps1` oppure `bash scripts/setup.sh`.
I file `.lock` fissano le versioni delle dipendenze verificate; `pyproject.toml`
ne dichiara gli intervalli di compatibilita. La verifica di un altro sistema
operativo resta affidata alla relativa esecuzione CI.

Dopo l'installazione, `python run_app.py` avvia il menu usando `.venv` se presente.
`python run_app.py demo` avvia direttamente la demo. Dall'ambiente attivato sono
disponibili anche `energy-planner` e `python -m energy_planner`.

## Demo offline

```bash
energy-planner demo --output-dir out/demo
energy-planner demo --objective peak --output-dir out/demo-peak
```

La demo genera `instance.json`, `solution.json`, `baseline.json` e `report.md`
nella directory scelta. Sono dati sintetici: non rappresentano un contratto,
una previsione di mercato o una validazione scientifica del modello.

## Chat

Copiare `.env.example` in `.env` e configurare **uno** dei provider:

- `LLM_PROVIDER=ollama`, `OLLAMA_HOST`, `OLLAMA_MODEL`;
- `LLM_PROVIDER=api`, `API_BASE_URL`, `API_MODEL`, `API_KEY`.

Poi eseguire:

```bash
energy-planner chat
energy-planner config show
```

La CLI legge soltanto il `.env` della directory corrente, senza sovrascrivere
variabili gia presenti nell'ambiente. Non includere mai `.env` in Git o negli ZIP.
Prompt predefiniti inclusi nel pacchetto; `PROMPTS_DIR` e un override opzionale.
Digitare `:quit` per terminare la chat.

Gli output operativi vanno in `out/` della directory corrente. Il launcher
`run_app.py` imposta invece la radice del progetto come directory corrente.

## Ottimizzazione e report

```bash
energy-planner optimize --input data/examples/demo_instance.json --output out/solution.json --objective cost --report
energy-planner report schedule --instance data/examples/demo_instance.json --solution out/solution.json --output out/report.md
```

L'istanza usa `pricing` come lista di valori per slot. CBC viene cercato in
`CBC_PATH`, nel `PATH` oppure nella distribuzione PuLP. Se non disponibile,
l'ottimizzatore segnala il problema e usa il fallback euristico esistente.
La demo e i test verificano esplicitamente il percorso CBC.

Per creare prezzi sintetici, ad esempio:

```bash
bash scripts/make_prices.sh Milano --flat 0.25
```

Su Windows: `./scripts/make_prices.ps1 -City Milano -FlatValue 0.25`.
I prezzi sono salvati in `data/prices/`, esclusa da Git.

## Dati, modelli e forecasting opzionale

Il candidato pubblico contiene esempi sintetici e un [manifest degli asset](data/asset-manifest.json).
I dataset e i modelli originali sono conservati in un archivio separato,
`innothon2025-assets-privati.zip`, e restano esclusi da Git anche se ripristinati.
La provenienza e i permessi di redistribuzione devono essere confermati dal team.

Vedere la [guida al forecasting](docs/forecasting.md) per installazione,
ripristino verificato tramite SHA-256, percorsi e limiti di riproducibilita.
Il file di snapshot originale e storico: non costituisce una previsione corrente.

## Test e controlli

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pytest -q
python scripts/check_repository.py
python -m build --no-isolation
python scripts/check_wheel.py
```

I test isolano sessioni e variabili locali e vietano la rete. Il controllo
del repository verifica sintassi, JSON, link relativi, nomi, dimensioni e
pattern di credenziali senza mostrarne i valori. Non sostituisce una revisione
manuale di dati o autorizzazioni.

Il [workflow CI](.github/workflows/checks.yml) prepara i controlli su Windows e Linux;
l'esecuzione su GitHub avverra dopo la pubblicazione autorizzata.

## Struttura

```text
energy_planner/     CLI, compilazione, conversazione, pricing e prompt inclusi
EnergyBot5/         ottimizzazione, euristica e report; namespace compatibile
optimization/      comandi storici di ottimizzazione corretti
price_forecaster/  codice ML opzionale; dati e modelli separati
data/examples/     JSON validi e dati sintetici
docs/              guide correnti, PDF e note storiche
legacy/notebooks/  notebook Gurobi originali, senza output salvati
spec/              specifiche tecniche originali
plan/              piani originali, conservati come riferimento storico
scripts/           setup, avvio, ripristino asset e verifiche
tests/             test offline
```

## Documentazione e licenza

- [Indice della documentazione](docs/README.md)
- [Sviluppo e verifiche](docs/development.md)
- [Compatibilita e migrazione](docs/migration.md)
- [Sicurezza](SECURITY.md)
- [Contributi](CONTRIBUTING.md)
- [Licenza MIT del codice](LICENSE)

La dichiarazione del codice mantiene la MIT gia presente nel pacchetto e usa
l'attribuzione collettiva "Innothon2025 contributors". Il team deve confermare
questa attribuzione prima della pubblicazione. La licenza non attribuisce
automaticamente diritti sui dati, modelli o documenti di terzi.
