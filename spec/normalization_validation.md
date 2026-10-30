# Normalization and Validation

## Normalizzazione
- `slot_minutes` e fissato a 5 per tutto il sistema; qualsiasi blocco che dichiari un valore differente genera subito un warning e viene riportato a 5.
- Orari e durate sono convertiti su multipli di 5 minuti tramite snap: arrotondare per difetto gli `start`, per eccesso gli `end` e adattare le durate. Se lo scarto e inferiore a 5 minuti la correzione e silenziosa, altrimenti si richiede conferma esplicita all utente.
- Espressioni temporali vaghe (es. "dopo pranzo", "sera") sono mappate su intervalli standard pre-configurati (ad esempio dopo pranzo = 13:00-15:00). Ogni intervallo derivato viene marcato con `meta.confidence = low` per segnalare la natura estimata del dato.
- Workforce: ogni turno dichiarato viene trasformato in un vettore E_l (capacita per slot) sommando le persone disponibili sui rispettivi intervalli. In assenza di triplette `workforce`, si applica un default `default_per_slot = 1` e si aggiunge una nota di assunzione.
- Prezzi: serie `per_hour` da 24 valori sono upsampled a `per_slot`, replicando ciascun valore su 12 slot consecutivi. Per un orizzonte di T ore, `per_slot` deve avere H = 12 * T elementi.

## Validazione
### Regole hard (bloccanti)
- Durata vs finestra: per ogni attivita, la durata normalizzata deve essere minore o uguale all ampiezza della finestra disponibile; violazioni impediscono la compilazione.
- Precedenze: il grafo diretto delle relazioni `precedes` deve essere aciclico. Il controllo prevede una visita topologica; la presenza di cicli genera errore bloccante e una richiesta di chiarimento all utente.
- Capacita personale: per ogni slot l della finestra di attivita, la somma `sum_i (e_i * z_i,l)` deve risultare minore o uguale a E_l. In caso contrario viene segnalato un errore e la pianificazione si arresta finche non si correggono workforce o assegnazioni.
- Macchine: attivita concorrenti che richiedono la stessa macchina devono risultare disgiunte sugli slot. Se la potenza dichiarata genera violazioni (es. superamento di limiti contrattuali), il validatore blocca il processo.

### Regole soft (correzioni sicure)
- Allargamenti di finestra inferiori o pari a 10 minuti ai due estremi sono proposti automaticamente e annotati in `meta.assumption`, lasciando proseguire la pipeline salvo rifiuto esplicito.
- Snap multipli di 5 minuti senza superare il vincolo di durata originale sono applicati direttamente e riportati nel report delle assunzioni.
- Se un valore `occurs_at` cade fuori dalla finestra dichiarata, la finestra viene riallineata all intervallo minimo `[occurs_at, occurs_at + durata]` e la correzione viene etichettata come `safe_adjustment`.

## Strategia di rete di sicurezza
- Prezzi mancanti: il sistema genera una serie flat con valore 0.25 per ciascun slot, aggiungendo una nota `assumption` che invita a sostituire il dato appena disponibile.
- Potenze macchina mancanti: ogni `machine:<id>` con `power_kW` assente riceve valore 0 e un warning in `meta` per ricordare l impatto sulle stime di picco.
- Durate o finestre mancanti: si assegnano durata di 30 minuti e finestra 08:00-18:00 marcate `meta.confidence = low`; queste assunzioni devono essere confermate nella successiva iterazione di dialogo.
