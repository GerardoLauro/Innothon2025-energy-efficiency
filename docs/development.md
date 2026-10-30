# Sviluppo e verifiche

Usare Python 3.12 e un ambiente dedicato. I file `requirements-base.lock` e
`requirements-dev.lock` registrano le versioni usate nella verifica Windows.
Gli intervalli di dipendenza e gli extra sono dichiarati in `pyproject.toml`.

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
python -m pytest -q
python scripts/check_repository.py
python -m build --no-isolation
python scripts/check_wheel.py
```

Il test della wheel installa il pacchetto in una directory temporanea e avvia
la demo da fuori repository; verifica che codice, prompt e fixture siano inclusi.
`build/`, `dist/`, cache, `.egg-info` e output non devono essere aggiunti a Git.

La CI usa la stessa procedura su Windows e Ubuntu con Python 3.12. Fino alla
prima esecuzione su GitHub, una configurazione CI non equivale a un esito positivo Linux.
L'installazione delle dipendenze e esplicita e puo richiedere Internet; i test
e la demo non contattano provider LLM o servizi meteo.

Per aggiornare le dipendenze: creare un nuovo ambiente, aggiornare gli intervalli,
rigenerare gli snapshot di versioni e rieseguire test, demo, build e verifica wheel.
Le librerie scientifiche opzionali richiedono una verifica distinta dei modelli.

Gli script Bash usano LF e vanno richiamati con `bash`, senza dipendere dal bit
eseguibile. Gli script PowerShell verificano l'esito dei comandi nativi.
