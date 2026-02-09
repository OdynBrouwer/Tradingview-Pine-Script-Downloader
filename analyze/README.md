# Analyze: JSON & scraping conventions ✅

Korte handleiding en afspraken voor de `analyze/` folder (NL):

## Waar staan de JSONs 📁
- Alle gegenereerde JSON-bestanden (inputs en outputs van scrapers / batches) **moeten** in:
  - `analyze/jsons/`
- Voorbeelden:
  - `analyze/jsons/indicators-urls.json` — URL-lijst (deduplicated)
  - `analyze/jsons/libraries-urls.json`
  - `analyze/jsons/strategies-urls.json`
  - `analyze/jsons/lib-pubdates.json` — samengevoegde pubdate-results

## Belangrijke scripts (kort) 🔧
- `analyze/extract_urls.py` — haalt alle URL-lijsten uit `pinescript_downloads/{indicators,libraries,strategies}/page-*.json` en schrijft:
  - `analyze/jsons/<category>-urls.json` (gebruik `--dedupe` om dubbele regels te verwijderen)

- `analyze/scrape_pubdates.py` — scraper die URLs pakt, publicatie-tekst parsed en `published_utc` normaliseert.
  - Aanbevolen test-run (sample):
    ```
    python analyze/scrape_pubdates.py --input analyze/jsons/indicators-urls.json --sample 100 --output indicators-pubdates-sample.json --delay 1.0
    ```
  - Als `--output` een bestandsnaam zonder pad is, wordt het bestand automatisch wegschreven naar `analyze/jsons/`.

- `analyze/run_libs_in_batches.py` — voorbeeld-runner die URL-lijsten in batches verwerkt en part-bestanden schrijft naar `analyze/jsons/`.
  - Standaard `--batch-size` is **100** en je kunt hervatten met `--start-batch`.
  - Resume voorbeeld:
    ```
    python analyze/run_libs_in_batches.py --batch-size 100 --delay 1.0 --start-batch 7
    ```

- `analyze/merge_lib_parts.py` — verzamelt alle `lib-pubdates-part-*.json` (kijkt in `analyze/jsons/`, `analyze/` en `scripts/`) en schrijft `analyze/jsons/lib-pubdates.json`.

- `analyze/analyze_lib_pubdates.py` — draait correlaties en korte rapportage op `analyze/jsons/lib-pubdates.json`.

## Conventies / regels 📋
- **Alle** JSON gerelateerde bestanden gaan in `analyze/jsons/` (inputs en outputs). Dit voorkomt verwarring tussen `scripts/` en `analyze/` runs.
- Gebruik `--dedupe` bij het aanmaken van URL-lijsten als je duplicates wilt verwijderen.
- Gebruik korte delays (bijv. `--delay 1.0`) om niet te veel requests in korte tijd te doen — pas aan als nodig.

## Troubleshooting & tips 💡
- Als een batch voortijdig stopt, run het batch-script met `--start-batch` op het volgende indexnummer; het slaat reeds bestaande part-bestanden over.
- Als je alleen snel wilt checken of selectors werken, gebruik `--sample 100` (snel) en controleer `analyze/jsons/<output>.json`.

---

Als je wilt voeg ik nog een korte `make`/PowerShell helper toe met standaardcommando's (extract → sample-scrape → merge → analyze). Wil je dat (Ja/Nee)? ✨
