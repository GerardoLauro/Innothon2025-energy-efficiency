# Instance Schema Specification

## Struttura generale
- Il JSON di istanza rappresenta un planning discretizzato su slot da 5 minuti; il numero totale di slot e H = 12 * T, dove T corrisponde all'orizzonte in ore.
- Ogni blocco principale descrive componenti indipendenti ma coerenti: tempo, prezzi, workforce, macchine, attivita, vincoli di lock, obiettivi, assunzioni.

## Campo `time`
- Include `slot_minutes = 5` come valore costante per l'intero documento.
- Contiene `H`, intero positivo, derivato dall'orizzonte temporale dopo normalizzazione e validazione.
- Puo riportare l'intervallo temporale originario (start, end) in formato `HH:MM`, utile per audit.

## Campo `pricing`
- Fornisce un vettore `c_l` di lunghezza H, dove ogni elemento rappresenta il costo dell'energia nello slot l.
- I valori provengono dal Price Engine: se il dato e stimato o flat, il campo `meta` associato ne riporta l'origine.
- Vincolo: il vettore deve essere completo; valori mancanti attivano fallback e vengono spiegati nelle `assumptions`.

## Campo `workforce`
- Contiene un vettore `E_l` con la disponibilita aggregata di personale per ciascuno slot.
- Il dato deriva dai turni dichiarati o da un default; include opzionalmente un oggetto `meta` con note su assunzioni.
- Vincolo: `E_l` >= 0 per tutti gli slot; il validatore garantisce coerenza con le attivita assegnate.

## Campo `machines`
- Lista di oggetti, ognuno con `id` (stringa univoca), `name` (descrizione leggibile), `power_kW` (valore numerico >= 0).
- Se la potenza e stimata o assente, il campo `meta.warning` segnala la condizione.
- Macchine senza `power_kW` confermato restano con valore 0 finche non si ottengono dati precisi.

## Campo `activities`
- Ogni attivita e rappresentata da un oggetto con:
  - `id` o `name`: identificativo univoco.
  - `duration_slots`: durata normalizzata espressa in numero di slot da 5 minuti.
  - `window_slots`: coppia `[start_slot, latest_start_slot]` con `0 <= start_slot <= latest_start_slot <= H - duration_slots`. Il primo elemento e lo slot piu precoce in cui l'attivita puo iniziare, il secondo e l'ultimo slot di start consentito. Le istanze generano automaticamente il campo ausiliario `window_end_slot = latest_start_slot + duration_slots` per indicare il termine della finestra.
  - `employees`: numero di risorse richieste per slot (`e_i`), >= 0.
  - `requires_machine`: opzionale, identificatore della macchina richiesta.
  - `precedences`: opzionale, lista di identificatori di attivita da completare prima.
- Opzionale `meta` include flag di confidence, origine dei dati e eventuali correzioni applicate.

## Campo `locks`
- Se presenti, definiscono vincoli rigidi su start di attivita o su slot specifici.
- Ogni lock riporta `start_at` con sotto-campi `activity` (id) e `time` (slot di riferimento) oppure `slot` assoluto.
- Lock incoerenti con la finestra generano validazioni bloccanti.

## Campo `objective`
- Indica il criterio principale (`min_cost` o `min_peak`).
- Puo includere sotto-sezioni per vincoli hard o soft aggiuntivi (es. `peak_cap`, `cost_budget`) con parametri specifici.
- Le preferenze sono calibrate in base alla tariffa selezionata e possono essere aggiornate a runtime.

## Campo `assumptions`
- Elenco ordinato di descrizioni testuali delle assunzioni applicate (prezzi flat, range temporali vaghi, potenze azzerate, ecc.).
- Ogni voce include eventuali riferimenti alla tripletta originale e al modulo che ha applicato il fallback.
- Il report viene esposto all'utente per confermare o rettificare i dati prima della generazione del piano.
