# Bioinformatics runtime resources

The repository retains pipeline code, environment definitions in `runtime/environments/`, and resource metadata in `manifest.json`. Databases, installed Conda environments, FASTQ files, model artifacts, application data and credentials remain outside Git.

## Preparing a new server

Create the two environments from their maintained definitions, choosing the installation prefixes configured for that server:

```bash
conda env create --prefix /srv/wgs-fmt/runtime/envs/fmt-tax --file runtime/environments/fmt-tax.yml
conda env create --prefix /srv/wgs-fmt/runtime/envs/fmt-func --file runtime/environments/fmt-func.yml
```

Prepare the reference databases and FMT matching/model resources listed in `manifest.json`, and configure the resource paths in the project `.env`. Installing the Python application environment does not install these bioinformatics resources.

## Historical migration tools

The former installer, checker, packager and restore scripts are preserved in the server-local, Git-ignored `deploy-backup/` directory. Their original relative paths are retained for historical inspection, and they are no longer maintained or directly runnable in the backup location. A new clone does not contain these backups. Existing resource bundles and datasets were not changed by deployment cleanup; use the resource manifest to verify versions when planning a migration.

Daily application operations use the four commands in [deploy/README.md](../../deploy/README.md). Application start and restart do not rebuild reference datasets or generate reports.
