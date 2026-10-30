# Triplette DSL Specification

## Struttura del blocco >>> SAVE
- Ogni blocco contiene un array ordinato di triplette.
- Una tripletta e composta da quattro campi: `soggetto` (stringa), `relazione` (stringa), `valore` (tipo semplice o oggetto), `meta` opzionale (oggetto con annotazioni).
- Il parser deve conservare l ordine di arrivo e associare il blocco a un timestamp di sessione.

## Soggetti ammessi
- `objective`: identifica il tipo di obiettivo globale.
- `horizon`: definisce l orizzonte di pianificazione espresso in ore.
- `time`: specifica configurazioni generali di slot minuti.
- `price`: fornisce serie di prezzo orarie (`per_hour` array da 24) o convertite per slot (`per_slot` lunghezza H, con H = ore * 12).
- `workforce`: descrive capacita del personale (shift con campi `start`, `end`, `people`) oppure default per slot.
- `machine:<id>`: dettaglia una macchina specifica (campi tipici `name`, `power_kW`).
- `activity:<name|id>`: rappresenta un attivita con attributi `duration_min`, `window` {`start`,`end`}, `occurs_at`, `employees`, `requires_machine`, `precedes`.
- `lock`: vincoli rigidi con struttura `start_at` {`activity`, `time`}.
- `note`: appunti di business, tipi `assumption` o `warning`.

## Regole sintattiche
- Soggetto e relazione devono essere stringhe ASCII senza spazi iniziali o finali.
- Relazioni ripetute sullo stesso soggetto sono ammesse; il parser applica le regole di conflitto descritte in seguito.
- Il campo `meta` e opzionale; quando presente contiene chiavi come `confidence`, `source`, `warning`, `superseded_by`.

## Regole semantiche principali
- Delta temporale fisso: tutti i calcoli assumono slot di 5 minuti (`time.slot_minutes = 5`).
- Orari in formato `HH:MM` zona Europe/Rome e devono essere allineati a multipli di 5 minuti.
- Se un attivita possiede un campo `occurs_at`, la finestra minima viene calcolata come `[occurs_at, occurs_at + duration_min]` e prevale su qualsiasi `window` piu ampia.
- Il grafo di precedenze costruito dai valori `precedes` deve essere aciclico; violazioni generano triplette `note` con tipo `warning` e richiedono conferma utente.
- Se il campo `power_kW` di `machine:<id>` non e fornito, impostare `0` e registrare in `meta.warning` che la potenza e sconosciuta.
- Serie di prezzo prive di lunghezza coerente con l orizzonte richiedono normalizzazione o fallback nel Price Engine.

## Normalizzazione temporale
- Tutti gli orari vengono convertiti a slot di 5 minuti mediante snap down/up a seconda della relazione (`start` arrotondato per difetto, `end` per eccesso).
- Range vaghi (es. "tardo pomeriggio") vengono trasformati in intervalli standard predefiniti (es. 16:00-18:00) e marcati con `meta.confidence = low`.
- Durate espresse in minuti devono essere multipli di 5; in caso contrario il Normalizzatore arrotonda e aggiunge una nota di assunzione.

## Policy di conflitto e assunzioni
- Quando due triplette con stesso soggetto e relazione sono incompatibili, il sistema crea una tripletta `note` con tipo `assumption` che spiega l assunzione applicata e chiede micro-conferma al successivo turno di dialogo.
- Se l utente fornisce una correzione, la tripletta precedente viene marcata in `meta` come `superseded_by` con riferimento alla nuova tripla.
- Conflitti su vincoli rigidi (es. `lock.start_at` duplicato) sospendono la compilazione finche l utente non conferma una delle opzioni.

## Esempi testuali di triplette ammesse
- Impostare l obiettivo: soggetto `objective`, relazione `primary`, valore `min_cost`.
- Definire orizzonte: soggetto `horizon`, relazione `hours`, valore `24`.
- Richiedere durata attivita: soggetto `activity:pressa01`, relazione `duration_min`, valore `90` con `meta.source = operator`.
- Occorrenze multiple: soggetto `activity:sanificazione`, relazione `occurs_at`, valori `06:00` e `18:00`, ciascuno con `meta.confidence` differenziato.
- Finestra vaga: soggetto `activity:verniciatura`, relazione `window`, valore `{start: "13:00", end: "17:00"}`, `meta.confidence = low`.
- Shift workforce: soggetto `workforce`, relazione `shift`, valore `{start: "08:00", end: "16:00", people: 5}`.
- Vincolo di lock: soggetto `lock`, relazione `start_at`, valore `{activity: "activity:assemblaggio", time: "09:30"}`.
- Nota di warning: soggetto `note`, relazione `warning`, valore "Potenza macchina M02 non dichiarata".

## Linee guida per l implementazione del parser
- Validare i campi obbligatori in base al soggetto (es. `activity` richiede almeno `duration_min`).
- Applicare normalizzazione degli orari e annotare ogni correzione in `meta`.
- Costruire grafo di precedenze e lanciare verifica aciclica durante la fase di validazione.
- Propagare fallback e avvisi nel report finale, includendo le triplette `note` generate automaticamente.
