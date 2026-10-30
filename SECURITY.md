# Sicurezza e dati locali

Usare `.env.example` come schema e conservare le credenziali in un `.env` locale
escluso da Git. Non pubblicare chiavi API, file di sessione o log con dati riservati.
Se una credenziale e stata condivisa in un archivio, rimuoverla dal pacchetto
non ne revoca l'accesso: il proprietario deve sostituirla presso il provider.

Eseguire `python scripts/check_repository.py` prima di preparare un commit.
Il controllo riconosce alcuni formati di segreti e non sostituisce la revisione
manuale. Non inserire mai il valore di una credenziale in issue o report pubblici.

Gli asset originali sono separati e vanno ripristinati solo da una fonte fidata.
I file pickle possono eseguire codice durante il caricamento: non sostituirli
con file di provenienza sconosciuta. Il ripristino controlla gli SHA-256 del manifest.

Segnalare problemi di sicurezza privatamente ai manutentori attraverso il canale
concordato dal team. Il progetto non dichiara un indirizzo di contatto non verificato.
