# DB Mount Prototype

This is an isolated prototype for splitting the large exam bank into domain DBs
and mounting only the desired DB files at runtime.

The current production app still uses `data/exam_bank.db` directly. This
experiment reads mounted DBs through `MountedExamRepository` and namespaces row
IDs as `mount_id::local_id` to avoid collisions across files.

## Current Main Snapshot

The frozen baseline is recorded in:

```text
data/main_snapshots/MAIN_SNAPSHOT.json
```

That manifest points to a read-only SQLite backup made before this prototype.

## Commands

Create a mount manifest for the frozen Main snapshot:

```powershell
.\.venv\Scripts\python.exe scripts\db_mount_prototype.py manifest `
  --snapshot data\main_snapshots\exam_bank.main_snapshot_YYYYMMDD_HHMMSS.db `
  --out experiments\db_mount_prototype\mount_manifest.local.json
```

Show mounted DB status:

```powershell
.\.venv\Scripts\python.exe scripts\db_mount_prototype.py status `
  --manifest experiments\db_mount_prototype\mount_manifest.local.json
```

Write a domain split dry-run plan:

```powershell
.\.venv\Scripts\python.exe scripts\db_mount_prototype.py plan `
  --db data\exam_bank.db `
  --out tmp\db_mount_domain_plan.json
```

Create domain DBs after reviewing the plan:

```powershell
.\.venv\Scripts\python.exe scripts\db_mount_prototype.py split `
  --db data\exam_bank.db `
  --out-dir data\domain_dbs `
  --manifest-out data\domain_dbs\mount_manifest.json `
  --apply
```

## Next Integration Step

Once the split plan is accepted, the app can add a DB mount selector before exam
selection. Read paths can use `MountedExamRepository`; write/import paths should
target exactly one selected DB.

