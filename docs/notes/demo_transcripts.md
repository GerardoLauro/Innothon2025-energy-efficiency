> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

# Demo Transcripts

## Caso A: FLEX/PUN Milano
**Assistente:** "Ciao! Confermi che lavoriamo su Milano?"
**Utente:** "Si, Milano."
```text
>>> SAVE
[
  ["price","city","Milano"],
  ["note","confirmation","Scenario impostato su Milano"]
]
```
**Assistente:** "Grazie. Che offerta stai usando?"
**Utente:** "Una Flex indicizzata PUN."
```text
>>> SAVE
[
  ["objective","primary","min_cost"],
  ["note","assumption","Offerta Flex indicizzata: obiettivo min_cost"]
]
```
**Assistente:** "Hai gia' i prezzi orari di oggi?"
**Utente:** "Si, li incollo ora."
```text
>>> SAVE
[
  ["price","per_hour",["0.25","0.26","0.27","0.28","0.29","0.30","0.31","0.32","0.33","0.34","0.35","0.36","0.37","0.38","0.39","0.40","0.41","0.42","0.43","0.44","0.45","0.46","0.47","0.48"]],
  ["note","confirmation","Prezzi caricati dall'utente"]
]
```
**Assistente:** "Quali attivita' scheduliamo?"
**Utente:** "Carico merci dalle 08:05 alle 09:35, dura 90 minuti e usa la pressa P1."
```text
>>> SAVE
[
  ["activity:carico","duration_min",90],
  ["activity:carico","window",{"start":"08:05","end":"09:35"}],
  ["activity:carico","requires_machine","machine:P1"]
]
```
**Assistente:** "Serve altro?"
**Utente:** "No, basta."
**Assistente:** "Riepilogo: Milano, obiettivo min_cost, prezzi importati, attivita' carico. Checklist: confermare workforce e potenza della pressa P1."

## Caso B: FIX/monoraria Roma
**Assistente:** "Buongiorno! Operiamo su Roma, confermi?"
**Utente:** "Si, Roma."
```text
>>> SAVE
[
  ["price","city","Roma"],
  ["note","confirmation","Scenario impostato su Roma"]
]
```
**Assistente:** "Che offerta utilizzi?"
**Utente:** "Fix monoraria."
```text
>>> SAVE
[
  ["objective","primary","min_peak"],
  ["note","warning","Offerta Fix: imposto min_peak"]
]
```
**Assistente:** "Quanta potenza contrattuale hai?"
**Utente:** "6 kW, abbiamo due lavastoviglie."
```text
>>> SAVE
[
  ["note","assumption","Potenza contrattuale 6 kW"],
  ["machine:lav1","name","Lavastoviglie A"],
  ["machine:lav1","power_kW",3],
  ["machine:lav2","name","Lavastoviglie B"],
  ["machine:lav2","power_kW",3]
]
```
**Assistente:** "Quando le fai girare?"
**Utente:** "Una alle 16, l'altra alle 18, durano mezz'ora."
```text
>>> SAVE
[
  ["activity:lavaggio-lav1","duration_min",30],
  ["activity:lavaggio-lav1","occurs_at","16:00"],
  ["activity:lavaggio-lav2","duration_min",30],
  ["activity:lavaggio-lav2","occurs_at","18:00"],
  ["note","confirmation","Lavastoviglie schedulate alle 16:00 e 18:00"]
]
```
**Assistente:** "Riepilogo: Roma, obiettivo min_peak, potenza 6 kW, due lavaggi alternati. Checklist: workforce, altri carichi energivori, conferma finestre."

## Caso C: prezzi incollati manualmente
**Assistente:** "Mi confermi la citta'?"
**Utente:** "Roma."
```text
>>> SAVE
[
  ["price","city","Roma"],
  ["note","confirmation","Scenario impostato su Roma"]
]
```
**Assistente:** "Non ho ancora prezzi orari: vuoi incollarli adesso?"
**Utente:** "Si, eccoli: 0.25,...,0.48"
```text
>>> SAVE
[
  ["price","per_hour",["0.25","0.26","0.27","0.28","0.29","0.30","0.31","0.32","0.33","0.34","0.35","0.36","0.37","0.38","0.39","0.40","0.41","0.42","0.43","0.44","0.45","0.46","0.47","0.48"]],
  ["note","confirmation","Prezzi orari incollati dal cliente"]
]
```
**Assistente:** "Perfetto, converto i dati in slot e aggiorno il piano. Vuoi procedere con workforce e attivita'?"
**Utente:** "Procediamo, ma conferma che i prezzi sono stati recepiti."
**Assistente:** "Si, ho generato 288 slot da 5 minuti partendo dai 24 valori orari. Possiamo passare al resto."
