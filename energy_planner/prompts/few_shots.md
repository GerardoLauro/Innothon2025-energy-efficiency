# Few-shot — Conversazione Energy Planner (prezzi interni, SAVE-STRICT)

---

### Esempio 1 — Città + Offerta FLEX (⇒ min_cost)
**Messaggio Utente:** Milano, ho un contratto flessibile indicizzato PUN.
**Risposta Assistente:** Ok: userò la previsione prezzi interna per Milano. Con l’offerta PUN ottimizziamo i costi. Procedo a chiederti personale e macchine?
>>> SAVE
[
  ["price","city","Milano"],
  ["objective","primary","min_cost"],
  ["note","assumption","Offerta ENEL_FLEX_BUSINESS_PUN_TRI"]
]

---

### Esempio 2 — Offerta FIX (⇒ min_peak) + potenza contrattuale
**Messaggio Utente:** Roma, prezzo fisso tutto il giorno, il contatore è da 30 kW.
**Risposta Assistente:** Perfetto: su prezzo fisso puntiamo a ridurre il picco. Registro il dato del contatore per riferimento.
>>> SAVE
[
  ["price","city","Roma"],
  ["objective","primary","min_peak"],
  ["note","assumption","Potenza contrattuale 30 kW"]
]

---

### Esempio 3 — Workforce a turni
**Messaggio Utente:** Siamo 5 la mattina e 3 il pomeriggio.
**Risposta Assistente:** Segno 08:00–16:00 con 5 persone e 16:00–22:00 con 3 persone.
>>> SAVE
[
  ["workforce","shift",{"start":"08:00","end":"16:00","people":5}],
  ["workforce","shift",{"start":"16:00","end":"22:00","people":3}]
]

---

### Esempio 4 — Città fuori elenco → sostituzione “vicina”
**Messaggio Utente:** Siamo a Bologna.
**Risposta Assistente:** Le città supportate sono Milano, Roma o Napoli. Uso Milano come riferimento (simulazione)?
>>> SAVE
[
  ["price","city","Milano"],
  ["note","assumption","Città Bologna non supportata: uso Milano (SIMULAZIONE)"]
]

---

### Esempio 5 — Macchine (kW noto e ignoto)
**Messaggio Utente:** Forno 4 kW e una lavastoviglie (kW non lo so).
**Risposta Assistente:** Ok, la lavastoviglie la segno temporaneamente senza potenza; potrai indicarla in seguito.
>>> SAVE
[
  ["machine:forno","name","Forno"],
  ["machine:forno","power_kW",4],
  ["machine:lavastoviglie","name","Lavastoviglie"],
  ["machine:lavastoviglie","power_kW",0,{"warning":"Potenza non dichiarata"}]
]

---

### Esempio 6 — Attività con due occorrenze fisse
**Messaggio Utente:** La lavastoviglie parte alle 16 e alle 18, dura mezz’ora.
**Risposta Assistente:** Perfetto: durata 30’ e due avvii fissi.
>>> SAVE
[
  ["activity:Lavastoviglie","duration_min",30],
  ["activity:Lavastoviglie","occurs_at","16:00"],
  ["activity:Lavastoviglie","occurs_at","18:00"],
  ["activity:Lavastoviglie","employees",0],
  ["activity:Lavastoviglie","requires_machine","machine:lavastoviglie"]
]

---

### Esempio 7 — Finestra “vaga” → range standard (low)
**Messaggio Utente:** Facciamo manutenzione dopo pranzo.
**Risposta Assistente:** La interpreto come 13:00–15:00 (se vuoi la stringo).
>>> SAVE
[
  ["activity:Manutenzione","window",{"start":"13:00","end":"15:00"},{"confidence":"low"}],
  ["note","assumption","Espressione vaga 'dopo pranzo' interpretata 13:00–15:00"]
]

---

### Esempio 8 — Precedenze + lock (chiude con un caso “neutro”, non Bologna)
**Messaggio Utente:** Prima impasto, poi cottura. La cottura deve partire alle 10:30.
**Risposta Assistente:** Registro la precedenza e il lock alle 10:30.
>>> SAVE
[
  ["activity:Impasto","precedes","activity:Cottura"],
  ["lock","start_at",{"activity":"Cottura","time":"10:30"}]
]
