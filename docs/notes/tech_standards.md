> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Tech Standards

- **Versione Python target**: 3.10+ (usa typing `|` e dataclass `slots=True`).
- **Dipendenze consentite**: standard library + `python-dotenv`; evitare framework web o client LLM non necessari.
- **Calcolo temporale**: rappresentare gli orari in minuti e slot da 5'; quando servono timezone usare `zoneinfo.ZoneInfo("Europe/Rome")`.
- **Stile di codice**: seguire PEP 8, type hints obbligatori, docstring sintetiche in italiano dove servono chiarimenti.
- **Logging**: usare `logging` con livello di default `INFO`; `--debug` deve portare a `DEBUG` senza logger custom.
- **Modello di errori**: riutilizzare le eccezioni esistenti (`PriceUnavailableError`, `SaveBlockError`, `ValidationIssue`) o estenderle; evitare nomi fittizi non implementati.
- **File binari**: vietato committare binari; i dataset di esempio restano in `data/`.
- **Convenzione CLI**: lanciare l'app con `python -m energy_planner.cli.app ...`; gli script in `scripts/` sono wrapper facoltativi.
