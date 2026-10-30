> Nota storica del pacchetto 2025. Per installazione, comandi e stato attuale usare il [README corrente](../../README.md). Alcune istruzioni e TODO sotto non descrivono la versione riorganizzata.

Manual Test Recipes for Pricing Integration
===========================================

1. CLI Forecast Export  
   Run `python -m energy_planner.cli.prices --city Milano --hours 24 --per-slot --out ./data/price_cache/milano.json`.  
   Expect a JSON result containing 24 hourly values and `per_slot` with 288 entries.

2. Conversational Flow  
   Start the chat via `python -m energy_planner.cli.app chat`.  
   Reply with: “Milano. Offerta Flex. Siamo 5 la mattina e 3 il pomeriggio. Lavastoviglie 30’ alle 16 e 18.”  
   After the city is confirmed, you should see a `>>> SAVE` block that includes `["price","per_hour", ...]`.

3. Instance Compilation  
   Execute `python -m energy_planner.cli.compile_instance --session-json ./out/session.json --city Milano --hours 24 --out ./out/instance_enriched.json`.  
   Expect the output to contain `pricing.per_slot` with 288 values and the notes reflecting the pricing source (e.g., Price_forecaster or flat fallback).
