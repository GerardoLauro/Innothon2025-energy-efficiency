> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Integrazione Previsioni Prezzi

## Fonte dati interna
- Il modulo interno fornisce previsioni orarie (24 valori) in EUR/kWh per Milano, Roma e Napoli, salvate in `data/prices/`.
- Ogni richiesta giornaliera restituisce una lista ordinata da 00:00 a 23:00; opzionalmente si puo' includere `date` (ISO `YYYY-MM-DD`) per distinguere i file.

## Formato atteso
- Input standard: `[v0, v1, ..., v23]` con separatore decimale `.`.
- Per gli incolli manuali il parser accetta sia `HH:MM valore` sia liste di numeri separati da virgola/spazio.

## Upsample verso gli slot
- La pipeline lavora su slot da 5 minuti: `upsample_hourly_to_slots` replica ogni valore orario su 12 slot consecutivi.
- Esempio: se alle 13:00 il valore e' 0.27 EUR/kWh, tutti gli slot 13:00-13:55 assumono 0.27.

## Gestione dati mancanti
- Se il servizio prezzi non risponde, l'assistente chiede all'utente i 24 valori o applica la serie flat 0.25 EUR/kWh registrando l'assunzione `note`.
- Il report ricorda di sostituire i prezzi simulati appena disponibili dati reali.

## Mapping citta' e validazione input
- La citta' e' case-insensitive: `milano`, `Milano`, `MILANO` sono equivalenti.
- Per citta' non supportate, l'assistente propone la localita' piu' vicina (Milano/Roma/Napoli), registra `["note","assumption","Citta <originale> non supportata: uso <scelta> (SIMULAZIONE)"]` e chiede conferma.
- Input ambigui (es. "Milan") vengono normalizzati con una conferma prima del salvataggio.
