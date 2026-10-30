# Test offline

Installare le dipendenze da `requirements-dev.lock`, poi il progetto in modalita
editable e avviare `python -m pytest -q` dalla radice.

Le verifiche coprono parser SAVE e guardrail originali, compilazione,
normalizzazione, tariffe, validazione e lettura dei prezzi. I test di regressione
verificano demo CBC e report per entrambi gli obiettivi, prompt inclusi,
mock finito, importazioni senza installazioni automatiche, caricamento differito
del forecaster e compatibilita tra JSON arricchito e ottimizzatore.

Ogni test usa una directory temporanea e non eredita credenziali locali.
La rete e vietata durante i test. Queste prove controllano integrazione e
comportamento software; non certificano l'accuratezza scientifica del modello.
