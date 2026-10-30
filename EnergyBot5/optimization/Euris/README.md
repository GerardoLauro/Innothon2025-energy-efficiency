# Euristica e strumenti di ricerca

`scheduler.py` e usato dal fallback dell'ottimizzatore corrente.
`ml_training.py` e `run_scheduler.py` sono strumenti originali di ricerca,
conservati senza modificare l'algoritmo sperimentale.

L'esecuzione del runner richiede gli input originali
`input_data_70_machines20.json`, `pun_forecast_20250608.json` e, per la variante
ML, `models/model_energy.pkl` nella directory di lavoro. Questi file non erano
presenti nel pacchetto consegnato. Il runner non e parte della demo supportata.

Per il training possono servire le dipendenze dell'extra `research` e ulteriori
input descritti nelle opzioni del modulo. Il Parquet originale e nell'archivio
separato degli asset. Non viene attestata riproducibilita degli esperimenti
storici in assenza degli input originali; il fallback operativo senza modello
usa il percorso attuale in `EnergyBot5/optimization/heuristic_fallback.py`.
