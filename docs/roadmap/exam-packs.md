# Exam Pack Distribution Roadmap

> Status: **planned separation**
>
> The application already supports local SQLite databases and image-inclusive `.examdb.zip` packages. This document defines how distributable question-bank content can be separated from the application source without changing the user's local-first workflow.

## Decision

Keep application code and database contracts in the main **Exam Generator** repository. Publish redistributable question-bank content as versioned **Exam Packs** outside the application source history.

The target ecosystem is:

```text
exam-generator
  application
  parser and importers
  database schema and migrations
  Exam Pack reader, validator, installer, and mount support
  small synthetic fixtures and an optional cleared demo pack

exam-generator-packs
  catalog and manifest schemas
  provenance and redistribution policy
  release notes
  GitHub Releases containing versioned .examdb.zip assets

optional exam-generator-mcp
  read-only access to locally installed Exam Packs
```

## Why the data should be separated

Repeatedly committing SQLite files or ZIP packages to the application repository causes several problems:

- binary history grows even when only a small part of the database changes;
- code releases and content releases become unnecessarily coupled;
- source-code licensing and source-document redistribution rights become harder to explain;
- users cannot update one subject or domain independently;
- private and public question banks are easy to mix accidentally;
- application clones become larger than necessary.

The application should remain usable with an empty local database. Exam Packs are optional content installed or connected by the user.

## What remains in the application repository

- SQLite schema and migrations;
- repository and validation layers;
- DB mount and import/export implementation;
- `.examdb.zip` package specification;
- pack compatibility checks;
- pack catalog client;
- small synthetic test fixtures;
- a minimal demo database only when every included item is cleared for redistribution.

## What moves to the pack repository

- redistributable question-bank databases;
- bundled question images and related assets;
- pack metadata and checksums;
- source provenance and rights classification;
- content changelogs;
- supported exam types and year coverage;
- minimum application and database-schema versions.

Actual binary pack files should be GitHub Release assets rather than ordinary Git commits.

## Proposed release layout

```text
Release: Maritime License Pack 2026.08

Assets:
  maritime-license-2026.08.0.examdb.zip
  maritime-license-2026.08.0.manifest.json
  maritime-license-2026.08.0.provenance.json
  SHA256SUMS
  CHANGELOG.md
```

## Pack manifest

A versioned manifest should accompany every pack.

```json
{
  "manifest_schema": 1,
  "pack_id": "maritime-license",
  "version": "2026.08.0",
  "display_name": "해기사 기출문제",
  "app_min_version": "1.2.0",
  "database_schema_version": 14,
  "question_count": 18420,
  "exam_types": ["3급항해사", "3급기관사"],
  "year_range": [2010, 2026],
  "contains_images": true,
  "rights_classification": "public-cleared",
  "asset": "maritime-license-2026.08.0.examdb.zip",
  "sha256": "<64 lowercase hex characters>"
}
```

Counts in the manifest must be generated from the sealed database, not entered manually. The release should fail if the manifest, package contents, schema, or checksum disagree.

## Installation flow

```text
Fetch catalog
  -> select pack
  -> download release asset
  -> verify SHA-256
  -> validate manifest and schema compatibility
  -> inspect package paths and asset references
  -> install under the local data directory
  -> register in the mount manifest
  -> expose through the normal question-bank UI
```

Installation must be atomic. A failed download, checksum mismatch, incompatible schema, invalid ZIP path, or missing image must not replace an existing working pack.

## Update and rollback

Each installed pack should retain:

- pack ID and version;
- package SHA-256;
- source release identifier;
- installation timestamp;
- previous known-good version when space permits.

Updates must not overwrite user-authored questions. Public packs should be treated as immutable content sources; personal edits should live in a separate writable user database or explicit overlay.

## Public and private packs

The package format can be shared while distribution remains separate.

### Public pack

- redistribution rights confirmed;
- no personal or school-internal information;
- provenance included;
- validation and content review completed;
- published through public releases.

### Private pack

- personal collections;
- school-internal materials;
- uncertain or restricted redistribution rights;
- user-created questions and explanations;
- stored locally, in a private repository, NAS, or institutional storage.

Exam Generator should mount both through the same local package contract. It should not upload a private pack automatically.

## Transitional repository artifact

Any existing `.examdb.zip` file committed in the application repository is transitional until it is classified as one of the following:

1. cleared demo pack;
2. distributable public pack to move into a release;
3. private or uncertain-rights content to remove from future source history.

No destructive cleanup is authorized by this roadmap alone. Classification, backup, migration, and verification must precede removal.

## MCP boundary

MCP is an access protocol, not a database storage or release format. It should be added only after the Exam Pack contract is stable.

A first MCP server should be local and read-only:

```text
list_exam_packs
get_pack_metadata
get_pack_statistics
search_questions
get_question
get_question_source
get_question_assets
build_question_selection
validate_selection
```

The initial surface should not expose arbitrary SQL, database replacement, deletion, or pack publication. Authoring and destructive changes remain in the desktop application until explicit write contracts and review gates exist.

## Delivery gates

1. **Pack specification** — manifest, package paths, checksum, and rights fields.
2. **Pack validator** — fail-closed validation of a local package.
3. **Catalog prototype** — resolve available versions without installing them.
4. **Atomic installer** — download, verify, install, register, and roll back.
5. **First cleared pack** — independently verified release asset.
6. **Repository cleanup** — only after the first external pack is installed successfully.
7. **Optional read-only MCP** — query locally mounted packs without changing them.

The main repository should not be renamed or existing database artifacts removed as part of this document-only foundation.
