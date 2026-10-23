# Private database backup and restore

Run these commands from the repository using its installed Python environment. Use explicit paths to your data; the examples below are placeholders. The destination parent folder must already exist. Keep backups outside the repository, frontend/public folders, and shared downloads.

On Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m playroom.backup backup --database "D:\Private\Playroom\playroom.sqlite3" --output "D:\Private\Backups\playroom-2026-10-23.sqlite3"
.venv\Scripts\python.exe -m playroom.backup restore --database "D:\Private\Backups\playroom-2026-10-23.sqlite3" --data-directory "D:\Private\Playroom-restored"
```

On other hosts use the same module and arguments with the installed environment's Python. Backup uses SQLite's backup API, including committed live WAL data, so it does not require stopping the source app. Do not manually copy only a running database's `.sqlite3` file. Integrity and foreign key checks run before publication. An existing output file or restore directory is refused, including empty directories. Symbolic links and Windows junctions in input/output paths are refused. Publication uses a same-filesystem hard link; filesystems without hard-link support fail without overwriting data.

The snapshot contains the entire database: accounts and password hashes, campaigns, original imported sources, profiles, memory, scenes, summaries, transcript revisions, immutable checkpoints, settings and cost evidence. It contains private story data and is **not encrypted**. Files/directories are created with private permissions where the OS supports them; on Windows use a private folder with appropriate NTFS access permissions. The tool does not alter directory ACLs or upload anything. Use snapshots from your own trusted installation; it is not an importer for untrusted SQLite files.

Provider credentials live in separate secret files and are **excluded**. A restore creates only `playroom.sqlite3` in a new directory. Use the same app version that created the backup (or a compatible newer version), stop the old local instance before opening the restored copy, and start the local runner against the new directory:

```powershell
.venv\Scripts\python.exe -m playroom.live_local --data-dir "D:\Private\Playroom-restored"
```

Log in again with your existing owner password. All saved sessions and active paid-trial approvals are revoked in the restored copy. Re-enter provider keys, verify/save new model profiles, select narrator/context roles again as appropriate, and explicitly approve any new paid trial. Do not point the restored app at the old secret folder. Startup itself does not authorize a provider request.

Restore changes the execution epoch, interrupts every unfinished generation (including queued jobs and complete-but-uncommitted candidates), interrupts queued/claimed/dispatched attempts and clears branch locks. Draft text, historical turns, checkpoints and cost reservations remain intact. Restored candidates cannot be committed automatically or manually as candidates; inspect the preserved draft before deliberately starting a new Send. The original database and snapshot remain unchanged.

Test recovery with a synthetic campaign before relying on a backup. This tool does not schedule backups, encrypt them, migrate credentials, restore in place, deploy, or change VPS/Caddy configuration.
