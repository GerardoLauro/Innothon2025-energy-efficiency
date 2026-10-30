> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Assumptions per la Simulazione

## Assunzioni di fallback attive oggi
- **Prezzi flat 0.25 EUR/kWh**: `energy_planner.core.normalization.build_price_series` applica la serie flat quando mancano i 24 valori orari o la cardinalita' non e' valida.
- **Workforce predefinita = 1 persona/slot**: in assenza di triplette `workforce | shift` viene usato `DEFAULT_WORKFORCE_PER_SLOT` e viene registrata l'assunzione corrispondente.
- **Potenza macchina sconosciuta = 0 kW (warning)**: il compilatore assegna 0.0 in `machine:<id> | power_kW` e il report aggiunge l'assunzione "Potenza non dichiarata".
- **Serie incollate manualmente**: `parse_user_hourly_series` accetta sia formati `HH:MM valore` sia liste numeriche; se il parse fallisce l'assistente chiede di reinserire i 24 valori.

## Tracciamento nel report delle assumptions
- Le assunzioni raccolte da normalizzazione e compilazione vengono inserite nel campo `assumptions` dell'istanza e riversate in `out/assumptions.txt`.
- `default_assumptions_from_context` aggiunge automaticamente le voci standard (flat price, workforce di default, potenza macchina 0 kW) per mantenere il report leggibile.
- Ogni fallback applicato e' esplicitato anche tramite triplette `["note","assumption","..."]`, cosi audit e debug rimangono tracciabili.

## Aggiornamento durante la chat
- Quando l'utente fornisce un dato reale, la nuova tripla sostituisce il fallback grazie alla deduplica del `TripleStore`.
- Le assunzioni risolte spariscono dal riepilogo successivo: il report include solo i fallback ancora attivi.
- L'assistente conferma ogni sostituzione con un blocco `>>> SAVE` e un messaggio sintetico che evidenzia la correzione.

## Linee guida per la micro-conferma
- Richiedere conferma esplicita quando un fallback impatta vincoli (es. aggiunta di un vincolo di picco, modifica della potenza contrattuale).
- Segnalare sempre l'applicazione di fallback strutturali (prezzi flat, workforce di default, potenza 0 kW) invitando l'utente a completare i dati.
- Per rettifiche minori entro il delta di 5 minuti o conferme ripetute e' sufficiente una nota informativa, lasciando comunque traccia nel report.
