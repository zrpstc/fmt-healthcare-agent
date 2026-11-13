# Runtime path configuration

All application-relative paths are resolved against the checkout, independently of the shell working directory.
`WGS_WORKSPACE` is the default runtime data directory. `WGS_FMT_RESOURCE_ROOT` overrides the shared resource directory and falls back to `FMT_ROOT`, then `WGS_WORKSPACE`.

`WGS_BIOINFORMATICS_ENV_ROOT` selects the relocated tool environments. `WGS_BIOINFORMATICS_DATABASE_ROOT` selects their databases. Legacy `ENV_ROOT` and `DB_ROOT` remain accepted when the corresponding canonical variable is unset. Set the database root explicitly when databases live outside the workspace.

Shell entry points load `.env` through `scripts/runtime_paths.py`, using the same Python resolver as the application. Already exported environment variables take precedence. The shell bridge exports an explicit list of path and pipeline settings; it does not export authentication fields.

`tool_environment()` and `wgs_run_tool` prepend the selected environment's `bin` and `lib` directories for the child process. This resolves libraries after a runtime relocation even when a binary retains an old ELF RUNPATH. Neither helper changes the global loader configuration. The worker and deployment check execute `glpsol --version` before accepting the runtime.

`WGS_RESULTS_DIR`, `WGS_BIOINFORMATICS_OUTPUT_ROOT`, `WGS_FMT_MATCHING_DIR`, and `WGS_FMT_TRIPLET_MODEL_DIR` override their respective data locations. Maintenance scripts use these same values. An explicitly configured missing database or result directory is not replaced with a directory from a different checkout.
