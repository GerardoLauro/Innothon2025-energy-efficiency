# Forecasting opzionale e asset originali

Il modulo ML non e necessario per la demo o per ottimizzare un JSON gia compilato.
L'importazione del codice non avvia addestramento. L'esecuzione diretta del
modulo di ricerca avvia invece la pipeline originale, che puo richiedere molto tempo.

## Installazione e ripristino locale

Dalla radice, nell'ambiente attivo:

```bash
python -m pip install -r requirements-forecasting.txt
python scripts/restore_assets.py /percorso/innothon2025-assets-privati.zip
python -m energy_planner.cli.prices --city Milano --hours 24 --per-slot --out out/prices.json
```

L'ultima operazione puo essere onerosa e usa i modelli originali, senza addestrarli.
Controllare sempre `meta.source` e `meta.simulazione` nel risultato: in caso di
dipendenze, file o modelli incompatibili viene restituito un fallback esplicito.
Gli snapshot storici sono contrassegnati come simulazione e `archived_snapshot`.

Il ripristino verifica dimensione e SHA-256 di tutti gli asset prima di scrivere,
rifiuta percorsi esterni alla destinazione e non sovrascrive file diversi senza
`--overwrite`. Il [manifest](../data/asset-manifest.json) e l'autorita locale
dei file consentiti; non viene sostituito con quello presente nello ZIP.

Le directory ripristinate rimangono escluse da Git. L'archivio privato contiene:

- tre CSV in `price_forecaster/datasets_folder/`;
- un modello `.pth` e due scaler `.pkl` in `price_forecaster/models/`;
- il dataset euristico `EnergyBot5/optimization/Euris/test.parquet`;
- lo snapshot storico `data/forecast_prices.json`.

La copia duplicata del CSV meteo nella vecchia `datasets_folder/` di radice e
stata eliminata dopo il confronto byte per byte; il file canonico e preservato.

## Percorsi e compatibilita

Il codice del forecaster si trova in `price_forecaster/code/Price_forecaster.py`;
dataset e modelli sono cercati nel relativo pacchetto `price_forecaster/`.
`PRICE_FORECASTER_ROOT`, se impostato, deve indicare la directory `code` oppure
il file Python. Per un'installazione wheel con dati esterni, impostarlo al
percorso assoluto del codice nella copia dove sono stati ripristinati gli asset.
La cache predefinita e `data/price_cache/` della directory corrente.

Il caricamento dei pesi NHITS originali e il percorso adapter sono stati provati
su CPU, con rete bloccata e senza addestramento. L'[ambiente di quella verifica](forecasting-check-environment.json)
registra le versioni usate; non e un lock di una nuova installazione pulita.

Le dipendenze ML hanno intervalli dichiarati in `pyproject.toml`; non si dichiara
riproducibilita dell'addestramento con tutte le combinazioni di versioni.
Gli scaler pickle richiedono librerie compatibili con quelle di origine:
non caricare file pickle provenienti da fonti non fidate. I pesi PyTorch sono
caricati con `weights_only=True` e mappatura CPU per evitare dipendenze dalla GPU originale.

L'accuratezza e la validita scientifica delle previsioni non sono state oggetto
della revisione per GitHub. I dati di origine e le autorizzazioni di diffusione
devono essere verificati dal team prima di qualunque caricamento pubblico degli asset.
