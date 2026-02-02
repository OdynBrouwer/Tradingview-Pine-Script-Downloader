# TradingView Pine Script Downloader — Batch Collection & Processing

Een helder, beknopt overzicht van de batch-verzamel- en verwerkingsstappen die we gebruiken om open-source Pine Scripts van TradingView te verzamelen en lokaal op te slaan.

> Dit document is bedoeld voor ontwikkelaars en beheerders die grootschalig URL-verzamelingen willen maken en vervolgens gecontroleerd willen downloaden.

---

## Wat doet dit project

- Verzamelt script-URLs van TradingView listing pagina's (indicators, libraries, strategies) in JSON-bestanden per pagina.
- Verwerkt die URL-lijsten en downloadt `.pine` bestanden met metadata en statusbestanden voor herstel.

## Belangrijkste features

- Batch-georiënteerde URL-collectie met `batch_download.py` (template-based)
- Gecontroleerde bulk-downloading via `batch_pages.py` (proces per pagina-map)
- Verbeterde extraction met `tv_downloader_enhanced.py` (zichtbare browser, multiple extraction methods)
- Eenvoudige onderhoudsscripts (`scripts/check_types.py`)

---

## Aan de slag — aanbevolen stappen

1. Verzamel URL-lijsten per categorie (gebruik de volgende commando's):

```bash
# Strategies
python batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=strategies&sort=recent_extended&page={n}" --start 1 --end 217 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads

# Libraries
python batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=libraries&sort=recent_extended&page={n}" --start 1 --end 61 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads

# Indicators
python batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=indicators&sort=recent_extended&page={n}" --start 1 --end 500 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads
```

2. Controleer een paar `page-XX-urls.json` bestanden (sanity check).
3. Verwerk pagina-mappen (bijv. 1..60):

```bash
python batch_pages.py --start 1 --end 60
```

4. Na de run: controleer `scripts/logs/` en voer `python scripts/check_types.py` voor `.pine` header validatie.

---

## Actuele scripts (kort overzicht)

- `tv_downloader_enhanced.py` — Hoofd downloader (aanbevolen), met diagnostics en resume-ondersteuning.
- `batch_download.py` — Template-gebaseerde URL-collectie (per categorie/pagina).
- `batch_pages.py` — Verwerk verzamelde `page-XX` mappen en download scripts per type.
- `download_from_json.py` — Download per-URL lijst (`page-XX-urls.json`).
- `scripts/check_types.py` — Controleer `.pine` headers en detecteer type-mismatches.
- `scripts/run_periodic_collection.ps1` — Windows PowerShell runner voor periodieke collectie (optioneel).

---

## tv_downloader_enhanced.py (kort)

Belangrijkste opties:
- `--url / -u` : TradingView scripts URL
- `--output / -o` : output directory
- `--delay / -d` : wachttijd tussen requests
- `--visible` : toon browser window (vereist voor correcte extractie)
- `--no-resume` : start zonder resume
- `--debug-pages` : extra logging
- `--dump-copy` / `--dump-copy-diagnostics` / `--write-diagnostics` : snelle capture modes en diagnostics
- `--positional-click` : experimentele methode
- `--status` : toon output status

Voorbeelden:
```bash
# Single download
python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/"

# Debug capture met diagnostics
python tv_downloader_enhanced.py --url <URL> --visible --dump-copy-diagnostics --write-diagnostics --output ./pinescript_downloads
```

Kleine code-opmerking:
- Er is een kleine SyntaxWarning gevonden in de broncode rondom een `.replace("\\/","/")` gebruik. De fix is eenvoudig (escapen of raw string) en wordt aanbevolen. Zie `tv_downloader_enhanced.py` rond regel ~1179.

---

## Onderhoud & checks

- Controleer `.pine` headers: `python scripts/check_types.py`
- Logs: `scripts/logs/` (per run timestamped)
- Suggestie: toevoeging van `scripts/cleanup_duplicates.py` (dry-run) voor duplicaat-detectie en veilige opruiming.

---

## Bijdragen & support

- Issues: open een issue voor bugs of gewenste features.
- PRs: maak feature branches en stuur een pull request met duidelijke omschrijving en tests (indien van toepassing).
- Code stijl: volg PEP8, voeg type hints toe wanneer mogelijk.

---

## License & auteurs

Bekijk de `LICENSE` en `AUTHORS` bestanden (indien aanwezig) voor licentie- en maintainer-informatie.

---

*Laat het weten als je wilt dat ik nu de `strategies`-collectie uitvoer en een rapport oplever.*

*Gemaakt op: 2026-02-02*
```bash
python batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=strategies&sort=recent_extended&page={n}" --start 1 --end 217 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads
```
- Wat het doet: doorloopt pagina's 1..217 en slaat per pagina een JSON-bestand op met de exacte script-URL's (zoals `pinescript_downloads/page-001/strategies/page-001-urls.json`).
- Reden: strategies-categorie is relatief groot; we verzamelen eerst enkel URLs (geen downloads) om later gecontroleerd te verwerken.
- Output: `pinescript_downloads/page-XXX/strategies/page-XXX-urls.json` per pagina.

2) Libraries (verzamel URLs)

```bash
python batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=libraries&sort=recent_extended&page={n}" --start 1 --end 61 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads
```
- Wat het doet: zelfde als hierboven maar voor libraries (1..61).
- Output: `pinescript_downloads/page-XXX/libraries/page-XXX-urls.json`.

3) Indicators (verzamel URLs)

```bash
python batch_download.py --template "https://www.tradingview.com/scripts/page-{n:02d}/?script_type=indicators&sort=recent_extended&page={n}" --start 1 --end 500 --max-pages 1 --fast --collect-urls-only --output pinescript_downloads
```
- Wat het doet: verzamel URLs voor indicators (grote set, 1..500).
- Output: `pinescript_downloads/page-XXX/indicators/page-XXX-urls.json`.

4) Verwerk de verzamelde pagina-mappen

```bash
python batch_pages.py --start 1 --end 60
```
- Wat het doet: zoekt in `pinescript_downloads/page-01` .. `page-60` naar `page-XX-urls.json` bestanden en roept per URL de downloader aan (`tv_downloader_enhanced.py`) om `.pine` bestanden te downloaden en metadata op te slaan.
- Let op: `batch_pages.py` detecteert type-subfolders (`indicators`, `libraries`, `strategies`) en plaatst downloads in diezelfde submappen.
- Output: `.pine` bestanden in `pinescript_downloads/page-XX/<type>/` plus `manifest.txt`, `metadata.json` en `.progress.json`.

---

## Aanbevolen volgorde (veilig en reproduceerbaar)

1. Run de 3 `batch_download.py`-commando's (strategies, libraries, indicators) om URL-lijsten te verzamelen.
2. Controleer een paar `page-XX-urls.json` bestanden handmatig (quick sanity-check) om te controleren of de URLs geldig zijn.
3. Run `python batch_pages.py --start 1 --end 60` (of het bereik dat je wilt) om de downloads uit die pagina-mappen te starten.
4. Na de run: controleer `scripts/logs/` en voer `python scripts/check_types.py` om `.pine` headers en type-mismatches na te lopen.

---

## Tips en waarschuwingen

- `--fast --collect-urls-only` verzamelt alleen URLs en is veel sneller en vriendelijker voor de server (geen downloads). Gebruik dit als eerste stap.
- Wees zorgvuldig met ranges: `indicators` is groot (1..500). Verdeel in batches als je dat prettiger vindt (bijv. 1..100, 101..200, ...).
- Respecteer rate limits: houd een redelijke marge als je later daadwerkelijk gaat downloaden (verlaag `--fast` niet zonder reden bij downloads).
- Backups: bewaar `pinescript_downloads` of verplaats naar een NAS voordat je grootschalig verwijdert of opschoont.

---

## Script: `tv_downloader_enhanced.py`

**Kort:** dit is de hoofd-downloader. Hij opent een zichtbare browser (clipboard-based extraction), ondersteunt voortgangsherstel (`--no-resume` om even níet te herstellen), en heeft een aantal diagnostische modi voor snellere captures of uitgebreidere logging.

Belangrijkste opties (kort):
- `--url / -u` : TradingView scripts URL (verplicht voor single runs)
- `--output / -o` : output directory (standaard `./pinescript_downloads`)
- `--delay / -d` : wachttijd tussen requests
- `--visible` : toon browser window (verplicht voor juiste extractie)
- `--no-resume` : start schoon (negeer `.progress.json`)
- `--max-pages / -p` : max aantal pagina's te scannen
- `--debug-pages` : extra pagina-logging
- `--dump-copy` / `--dump-copy-diagnostics` / `--write-diagnostics` : snelle dump-copy capture modes en optioneel diagnostics schrijven
- `--positional-click` : experimentele, snelle click-methode (fragiel)
- `--status` : toon status van de output directory en exit

Voorbeelden:

```bash
# Single download (aanbevolen)
python tv_downloader_enhanced.py --url "https://www.tradingview.com/scripts/luxalgo/"

# Snelle capture met diagnostics (geschikt voor bulk debugging)
python tv_downloader_enhanced.py --url <URL> --visible --dump-copy-diagnostics --write-diagnostics --output ./pinescript_downloads

# Start zonder voortgangsherstel
python tv_downloader_enhanced.py --url <URL> --no-resume

# Check output status
python tv_downloader_enhanced.py --output ./pinescript_downloads --status
```

Kleine code-opmerking / waarschuwing:
- Tijdens code-inspectie is een kleine SyntaxWarning gevonden in `tv_downloader_enhanced.py`:

```
C:\GIT\Tradingview-Pine-Script-Downloader\tv_downloader_enhanced.py:1179: SyntaxWarning: invalid escape sequence '\/'
  source = source.replace('\"', '"').replace('\/', '/')
```

- Oplossing: gebruik dubbele backslash of raw string zodat Python geen invalid escape sequence rapporteert, bijv. `source = source.replace('\\/','/')` of `source = source.replace(r'\/', '/')`.
- Na de fix: voer `python scripts/check_types.py` uit en/of run een korte lint/type-check.

---

## Verificatie & onderhoud

- Na downloads: run `python scripts/check_types.py` en los eventuele mismatches handmatig op.
- Logs: bekijk `scripts/logs/` voor fouten en waarschuwingen.
- Indien nodig: schrijf een kleine `scripts/cleanup_duplicates.py` (dry-run) om dubbele `.pine` bestanden op te sporen en te rapporteren alvorens te verwijderen.

---

## Juridisch & Ethiek

- **Respecteer auteursrechten en TradingView's regels:** download alleen scripts die expliciet open-source of openbaar beschikbaar zijn. Gebruik deze tool niet om toegang te verkrijgen tot beschermde of invite-only scripts.
- **ToS naleving:** zorg dat je gebruik van deze tool niet in strijd is met TradingView's Terms of Service of de licenties van de script-auteurs.
- **Geen misbruik of herdistributie zonder toestemming:** herverpakken of commercieel verspreiden van andermans code zonder expliciete toestemming is niet toegestaan.
- **Attribueren en respecteren van licenties:** respecteer de licentievoorwaarden in de bronbestanden en geef altijd correcte attributie wanneer je andermans code gebruikt.
- **Rate limiting en beleid:** wees verantwoordelijk — beperk de snelheid van requests, gebruik `--fast` alleen voor URL-collectie en niet voor grootschalige downloads zonder zorgvuldige planning.
- **Geen omzeiling van beveiliging:** deze tool is niet bedoeld om beschermingsmechanismen te omzeilen. Pogingen daartoe wordt afgeraden en kunnen juridische gevolgen hebben.

Als je juridisch advies nodig hebt over specifieke gebruiksgevallen, raadpleeg een jurist; deze sectie is geen juridisch advies.

---

## Contact / Volgende stappen

Als je wilt, voer ik de batch-collecties uit in deze volgorde en lever ik een kort rapport (aantal URLs per pagina, aantal succesvolle downloads, errors) na elke stap. Geef "start" en ik begin met de `strategies`-collectie.

---

*Gemaakt op: 2026-02-02*