# Verwijderde-scripts workflow

Korte handleiding voor het detecteren van door TradingView verwijderde (ghosted) scripts en het verplaatsen van lokale `.pine` bestanden naar per-category `remove` mappen.

Stappen (voer uit vanaf de repository root):

1) Haal categorie-URLs opnieuw op

```powershell
python analyze/extract_urls.py --categories indicators libraries strategies
```

2) Bouw of werk de master `all-urls.json` bij

```powershell
python analyze/build_all_urls.py --categories indicators libraries strategies
```

3) Voer de snelle, incrementele checker uit (skip reeds-gecheckte URLs)

```powershell
python analyze/check_removed_fast.py --source analyze/jsons/all-urls.json --only-new --concurrency 12 --head-first --timeout 8 --progress analyze/jsons/removed-scan-state.json --output analyze/jsons/removed-fast.json
```

- Belangrijk: bewaar `analyze/jsons/removed-scan-state.json` — dit bestand zorgt dat `--only-new` niet alles opnieuw checkt.
- Optioneel: voeg `--max-age-days N` toe om alleen items ouder dan N dagen opnieuw te controleren.

4) Zoek lokaal gematchte `.pine` bestanden (heuristisch)

```powershell
python analyze/scripts/find_local_matches.py
```

- Output: `analyze/jsons/removed-local-matches.json` (lijst met URL → gevonden lokale paden).

5) Verplaats lokaal gematchte bestanden naar per-category `remove` map

Dry-run: bekijk `analyze/jsons/removed-local-matches.json` en `analyze/jsons/removed-moved.json` voordat je verandert.

Als je wilt verplaatsen (automatisch):

```powershell
python analyze/scripts/move_local_matches.py
```

- Resultaat: `analyze/jsons/removed-moved.json` met verplaats-log en eventuele fouten.

6) Opschonen (optioneel)

- Als sommige bestanden dubbel in `remove/remove` terechtkomen, kun je ze één niveau omhoog verplaatsen met PowerShell (voorbeeld):

```powershell
Get-ChildItem -Recurse -Directory -Filter remove | ForEach-Object {
  $child = Join-Path $_.FullName "remove"
  if (Test-Path $child) {
    Get-ChildItem $child -File | ForEach-Object { Move-Item $_.FullName ($_.Directory.Parent.FullName) -Force }
    Remove-Item $child -Recurse -Force
  }
}
```

Belangrijke outputbestanden

- `analyze/jsons/all-urls.json` — master URL lijst
- `analyze/jsons/removed-fast.json` — volledige scanresultaten
- `analyze/jsons/removed-fast-urls.txt` — compacte lijst met URLs die als verwijderd zijn gemarkeerd
- `analyze/jsons/removed-local-matches.json` — gevonden lokale `.pine` matches
- `analyze/jsons/removed-moved.json` — log van verplaatste bestanden

Tips en aanbevelingen

- Draai de pipeline periodiek (bijv. 2×/dag). Op Windows kun je Task Scheduler gebruiken met de drie hoofdcommando's (extract → build_all → check_removed_fast).
- Test eerst met `--only-missing` of `--only-new` en met lagere `--concurrency` als je netwerkinstabiliteit ziet.
- Houd `removed-scan-state.json` veilig (versiebeheer/backup) om onnodig opnieuw scannen te voorkomen.
- Als je de periodieke Task Scheduler wrapper `scripts/run_periodic_collection.ps1` gebruikt: deze forceert UTF-8 output (vermijdt `cp1252` UnicodeEncodeError bij log-redirects) en gebruikt een **60 minuten** stale-lock threshold om te voorkomen dat taken elkaar overlappen wanneer een run langer dan 15 minuten duurt.

Als je wil dat ik dit README nog in het Nederlands uitbreid met screenshots of specifieke Task Scheduler stappen, zeg het even.
