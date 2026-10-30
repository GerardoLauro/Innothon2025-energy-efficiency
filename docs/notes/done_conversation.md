> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Conversazione Release Checklist
- [ ] Avvio `python -m energy_planner.cli.app chat` funziona con provider Ollama e API
- [ ] Conversazione <=7 turni produce `out/instance.json`
- [ ] `out/assumptions.txt` presente quando vengono applicate assunzioni
- [ ] Prezzi citta' mancanti -> scelta incolla/flat senza bloccare
- [ ] Workforce sempre definita (turni oppure default per slot)
- [ ] Almeno un'attivita' schedulabile (durata multipli di 5', finestra coerente)
- [ ] Precedenze acicliche (o ciclo risolto)
- [ ] Messaggi di errore chiari per blocchi `>>> SAVE` e vincoli
- [ ] README / Quickstart coerenti con il flusso attuale
- [ ] Demo transcript aggiornata e replicabile
