# scripts/

Scripts die de runner, cleanup en (optioneel) diagnosetools bevatten.

Current files and status
- `run_periodic_collection.ps1` — PowerShell runner voor geplande runs (actief/onderhoud).
- `run_collection.bat` — simpele wrapper voor Windows scheduling.
- `cleanup_logs.ps1` — logopschoning (aanbevolen, actief en aangeroepen door de runner).
- `simulate_timeout.ps1` — testscript om timeout/kill flow te valideren (diagnostisch).
- `update_task_settings.ps1` — helper voor Task Scheduler instellingen (operational).
- `tv-collection.xml` — Task Scheduler export (referentie).
- `check_strategies.py` & `check_types.py` — kleine analysis helpers voor sanity checks van `.pine` headers; kunnen worden ge-archiveerd als ze niet meer nodig zijn.
- `logs/` — contains timestamped run logs (opgeruimd door `cleanup_logs.ps1`).

Aanbeveling
- Houd operationele scripts (runner, cleanup, scheduling helpers) in `scripts/`.
- Verplaats analyse-only helpers (`check_strategies.py`, `check_types.py`) naar `analyze/archived/` als je ze niet meer dagelijks gebruikt; ik kan dat voor je verplaatsen en een korte reden toevoegen per bestand.
- Kalibreer `cleanup_logs.ps1` retention naar je behoefte (standaard nu 4h in runner).

Wil je dat ik de archiveringsactie uitvoer (verplaatsen van genoemde helpers naar `analyze/archived/`)? Geef 'move' en ik doe het, of geef 'docs' en ik voeg alleen de READMEs/notes.