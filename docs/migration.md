# Migrazione dal pacchetto originale

La radice GitHub contiene direttamente README, licenza, dipendenze e sorgenti.
Le due cartelle involucro e i RAR annidati non fanno parte del repository pubblico.
Non viene riutilizzata la vecchia `.git`: conteneva un ambiente virtuale tracciato
e non rappresentava tutti i file consegnati.

Il comando canonico e `energy-planner`, equivalente a `python -m energy_planner`.
Restano disponibili i namespace storici per compatibilita:

```bash
python -m EnergyBot5 --help
python -m EnergyBot5.main --mode opt --input data/examples/demo_instance.json --output out/solution.json
python -m EnergyBot5.optimization.minimizzazione_costo --input data/examples/demo_instance.json --output out/cost.json
python -m EnergyBot5.optimization.minimizzazione_picco --input data/examples/demo_instance.json --output out/peak.json
python -m EnergyBot5.reporting.schedule_report --instance data/examples/demo_instance.json --solution out/solution.json --export out/report.md
```

Gli avvii storici non installano piu pacchetti o solutori. `run_app.py` usa la
`.venv` locale se esiste; il setup va eseguito prima, come descritto nel README.

I prompt sono inclusi in `energy_planner/prompts/`; lasciare `PROMPTS_DIR` vuoto
per il percorso predefinito. Gli output reali e i file di sessione originali non
sono esempi pubblici. La demo sintetica li sostituisce nei percorsi di prova.

Il comando `energy_planner.cli.compile_instance` mantiene il formato canonico
di `pricing`: lista per slot, compatibile con l'ottimizzatore.
I notebook storici sono ora in [legacy/notebooks](../legacy/notebooks/).

Le vecchie interfacce sperimentali in `energy_planner/scheduler/` rimangono
segnaposto e non sono usate dai comandi correnti. Il solver operativo e in
`EnergyBot5/optimization/optimizer_core.py`, con il relativo fallback euristico.
