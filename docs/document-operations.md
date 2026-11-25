# Private document operations

LexFlow accepts PDF, Word DOCX, UTF-8 TXT, JPEG, and PNG files of at most 10 MiB.
A document's file is immutable. Upload a separate document to replace it and archive
the previous one when appropriate. Authorized users find archives through the
**Archived** filter in the case's document list.

## Hosted scanning and storage

- Set `DJANGO_PRIVATE_MEDIA_ROOT` to a persistent directory writable only by the
  application account. Serve only `STATIC_ROOT` through the web server. Use the host's
  private temporary storage for Django's staged uploads. Limit multipart requests
  at the reverse proxy to 10,551,296 bytes.
- Install ClamAV and configure `clamd` with a local Unix socket accessible to the
  application account. Set `DJANGO_CLAMDSCAN_PATH` to the absolute path of
  `clamdscan`. Keep the daemon and its signatures updated. Enable
  `AlertExceedsMax yes` and configure `MaxFileSize` and `MaxScanSize` to cover
  the application's 10 MiB files and up to 40 MiB of expanded DOCX content. Set
  the worker and upstream timeouts to accommodate the application's 30-second scan
  limit plus upload and validation time.
- Uploads stay in a private temporary file until validation and scanning succeed.
  A detection rejects the upload. An unavailable scanner, timeout, or scan error
  returns a retryable response and leaves no downloadable file. Use
  `scan_existing_documents` to verify existing local or migrated files before
  serving them in hosted mode. Files missing from storage or failing the scan
  stay blocked.
- Run `uv run python manage.py cleanup_orphan_documents` to count generated files
  older than 24 hours without a matching document row. Pass `--delete` to remove
  them. This also preserves archived files. Let the host clean up stale temporary
  files after interrupted uploads.

[OWASP file upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
[ClamAV scanner setup](https://docs.clamav.net/manual/Usage/Scanning.html)

## Backup and recovery

Install `pg_dump` and `pg_restore` compatible with the database version. Run the
backup command with your normal Django settings and an existing restricted backup
destination, ideally on encrypted storage with access limited to backup operators.

```sh
uv run python manage.py backup_lexflow /path/to/private/backups
```

Each completed backup directory contains `database.dump` and `documents.tar`.
The command obtains both from the same PostgreSQL snapshot and checks that each
referenced file exists at the recorded size. Keep both files together. Schedule the
command using your deployment's backup scheduler and test restoration before relying
on the backup. [PostgreSQL pg_dump documentation](https://www.postgresql.org/docs/current/app-pgdump.html)

To verify a backup, use a fresh recovery database and an empty private media directory.
Restore the database with `pg_restore --exit-on-error --no-owner --dbname recovery_db database.dump`
using the appropriate PostgreSQL connection variables. Extract the matching, trusted
`documents.tar` with `umask 077` and `tar -xf documents.tar -C /path/to/recovery/private-media`.
Configure the isolated recovery app to use those two restored locations. Check document
downloads for both active and archived records with an authorized member and confirm
a copied link fails for a different user before reopening service.


### Automated restore drill

The shared check runs [RecoveryTests](../tests/test_recovery.py) with compatible
`pg_dump` and `pg_restore` on PATH. It backs up isolated synthetic records and
private files, restores them into a uniquely named temporary PostgreSQL database
and empty media directory, compares SHA-256 hashes, verifies linked relationships,
and checks authorized/unauthorized active and archived downloads. The recovery
database is dropped in `finally`; the development database and files are not
restored over. See [test results](test-results.md) for the latest evidence and
production recovery limitations.
