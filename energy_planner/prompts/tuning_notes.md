# Prompt Tuning Notes

## Migliorare l'intervista
- Aprire sempre con le tre domande chiave (città, offerta, potenza) nello stesso turno: es. "Siamo a Milano o preferisci Roma/Napoli?" seguito da "Che offerta stai usando (Fix, Flex, PLACET)?" e "La potenza contrattuale è nota?".
- Quando l'utente è incerto, riformulare con esempi concreti: "Non preoccuparti, puoi dirmi se l'offerta è a prezzo fisso (Fix) o indicizzata PUN (Flex)?".
- Proporre opzioni esplicite e brevi: "Preferisci incollare i 24 prezzi oppure usare la serie flat di test?".

## Massimizzare la densità dei blocchi SAVE
- Invita l'utente a fornire più dettagli in un'unica risposta: "Puoi indicarmi durata, finestra e macchina per l'attività in un solo messaggio?".
- Quando l'assistente conferma, raggruppare i fatti in un unico `>>> SAVE` con più triplette (objective, price, note) per ridurre i turni.
- Se l'utente fornisce una lista, trasformarla in triplette multiple nello stesso blocco (ad es. workforce shift + default).

## Evitare loop e stalli
- Se mancano i prezzi, proporre sempre due alternative: "A) incolla i 24 valori, B) uso la serie flat 0.25" e ricordare che può essere corretto in seguito.
- Dopo un warning (es. potenza mancante), chiedere conferma una sola volta e in caso di rifiuto registrare una nota `assumption` per evitare ripetizioni.
- Se l'utente rimanda una risposta, annotare `note | assumption` con la richiesta aperta e passare alla domanda successiva.
