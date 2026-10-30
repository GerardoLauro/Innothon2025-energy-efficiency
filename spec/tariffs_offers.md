# Tariffs and Offers

## Famiglie di offerta per PMI
1. **Prezzo fisso monorario**: copre prodotti con prezzo dell'energia bloccato e unico su tutte le ore (es. offerte "Fix" o equivalenti).
2. **Indicizzata PUN con fasce**: include soluzioni a prezzo variabile legate al PUN con articolazione tri-oraria F1/F2/F3 e contributo fisso.
3. **PLACET fissa**: tariffe a condizioni equiparate con prezzo dell'energia fisso per tutta la durata contrattuale.
4. **PLACET variabile**: versioni indicizzate PUN o analoghe con componente variabile e struttura regolata dal contratto PLACET.

## Scelta dell'obiettivo
- Offerte a prezzo fisso monorario o PLACET fissa -> l'obiettivo primario diventa `min_peak`, riducendo il picco di potenza assorbita per contenere i costi di punta.
- Offerte indicizzate PUN e PLACET variabile -> l'obiettivo primario e` `min_cost`, con possibilita` di aggiungere un vincolo secondario sul picco quando richiesto dall'utente o dal contratto.

## Classificazione robusta dei nomi commerciali
- I nomi di marketing possono variare; il classificatore deve riconoscere sinonimi e pattern (es. termini come "fissa", "mono-oraria", "variabile", "PUN", "F1/F2/F3").
- L'algoritmo deve pesare combinazioni di parole chiave, descrizioni e note contrattuali per assegnare l'offerta alla famiglia corretta.
- E' consigliabile registrare il testo originale dell'offerta in `meta.source` per audit e future riletture.

## Potenza contrattuale
- Quando la potenza contrattuale (kW) e` dichiarata o indicata come criticita`, aggiungere un vincolo di picco massimo coerente con il valore fornito.
- In mancanza di dato esplicito, l'assistente propone un valore di default basato sulla categoria d'utenza e richiede conferma all'utente prima di applicarlo.
- Se il vincolo viene introdotto, il solver dovra` monitorare sia `min_peak` sia eventuali penalita` per superamenti di potenza.
