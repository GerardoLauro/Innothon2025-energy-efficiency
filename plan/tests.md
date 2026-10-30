# Test Plan

## Scenario 1: Milano + FLEX indicizzata
- Conversazione attesa: l'assistente chiede citta, offerta, prezzi. L'utente fornisce Milano, Flex indicizzata PUN, incolla 24 valori; descrive due attivita (es. "carico" e "lavaggio") con durate e finestre coerenti, e dichiara una macchina. L'assistente imposta l'obiettivo su min_cost.
- Triplette `>>> SAVE` attese:
  - Obiettivo `min_cost`, citta Milano, nota di conferma tariffa.
  - Prezzi 24h trasformati in per_slot, con meta che indica origine utente.
  - Due attivita con `duration_min`, `window`, eventuali precedenze, e la macchina associata.
  - Macchina con `name`, `power_kW` dichiarata.
- Controlli di validazione: orari allineati a 5 minuti, precedenze acicliche tra le due attivita, capacita workforce default = 1 se non specificata, uso della macchina senza sovrapposizioni problematiche.
- Struttura istanza attesa: `time` con H coerente, `pricing` popolato con H elementi, `workforce` default, `machines` con 1 entry, `activities` con due oggetti, `objective` = min_cost, `assumptions` vuoto.

## Scenario 2: Roma + FIX monoraria
- Conversazione attesa: l'assistente registra Roma, offerta Fix monoraria, potenza contrattuale 6 kW; l'utente descrive due macchine energivore e due attivita che richiedono le macchine con finestre sovrapposte. L'assistente imposta min_peak e invita a risolvere la sovrapposizione.
- Triplette `>>> SAVE` attese:
  - Obiettivo `min_peak`, nota sulla potenza contrattuale.
  - Macchine `machine:M1`, `machine:M2` con `power_kW` specificata.
  - Attivita con `requires_machine`, finestre sovrapposte che generano warning; eventuali lock o suggerimenti per spostamenti.
  - Note di warning per superamento potenza se non risolto.
- Controlli di validazione: verificare conflitto di capacita macchina (disgiunzione mancante), controllo su picco di potenza (due macchine attive oltre 6 kW), richiesta di correzione. Validazione deve bloccare se l'utente non aggiusta le finestre.
- Struttura istanza attesa: `pricing` flat o derivato, `workforce` default, `machines` con due voci, `activities` con due elementi e vincoli, `objective` = min_peak, `assumptions` include eventuali fallback.

## Scenario 3: Napoli + PLACET variabile
- Conversazione attesa: l'assistente registra Napoli, offerta PLACET variabile, l'utente non dispone dei prezzi; il sistema applica serie flat 0.25. Vengono definite alcune attivita base. L'assistente annota la presenza di assunzioni.
- Triplette `>>> SAVE` attese:
  - Obiettivo `min_cost`, citta Napoli.
  - Nota `assumption` per prezzi flat, workforce default se non fornita.
  - Attivita con durate/finestra standard se mancano dati specifici.
- Controlli di validazione: confermare che i fallback siano applicati, orari e durate convertiti, assenza di precedenze problematiche. Il validatore deve segnalare l'assunzione dei prezzi e richiedere conferma.
- Struttura istanza attesa: `pricing` con valori flat, `workforce` default, `activities` con dati normalizzati, `objective` = min_cost, `assumptions` popolate con prezzi flat e altri fallback.

## Smoke test per blocchi `>>> SAVE`
- Verificare che blocchi senza intestazione `>>> SAVE` siano scartati con messaggio chiaro.
- Testare triplette mancanti di soggetto o relazione: il parser deve rifiutarle e spiegare l'errore.
- Gestire contenuto extra dopo le triplette (es. testo libero): confermare che venga ignorato o trasformato in note separate.
- Verificare che duplicati conflittuali generino note di assunzione o richiedano micro-conferma.
