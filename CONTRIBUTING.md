# Contribuire

Usare Python 3.12 e seguire la [guida di sviluppo](docs/development.md).
Prima di proporre modifiche eseguire test offline, controlli strutturali e build.
Descrivere problema, comportamento risultante e verifiche effettuate.

Modifiche a prompt e DSL devono mantenere coerenti [specifiche](spec/), parser,
compilatore ed esempi. I prompt distribuiti sono in `energy_planner/prompts/`.
Per nuove dipendenze aggiornare `pyproject.toml` e gli snapshot pertinenti.

Non aggiungere `.env`, credenziali, ambienti virtuali, output di sessione,
dataset originali o modelli senza un'esplicita revisione del team.
