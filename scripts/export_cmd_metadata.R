#!/usr/bin/env Rscript
# Export the official sampleMetadata data.frame with base R only.
# No package installation, namespace loading, FASTQ download or healthy filtering.

main <- function() {
    args <- commandArgs(trailingOnly=TRUE)
    output_dir <- "var/reference-sources/cmd"
    if (length(args)) {
        if (length(args) != 2L || args[[1L]] != "--output-dir")
            stop("Usage: Rscript scripts/export_cmd_metadata.R [--output-dir DIRECTORY]")
        output_dir <- args[[2L]]
    }
    options(timeout=max(180, getOption("timeout", 60)))
    dir.create(output_dir, recursive=TRUE, showWarnings=FALSE)
    if (file.access(output_dir, 2) != 0L) stop("Output directory is not writable")
    output_dir <- normalizePath(output_dir, mustWork=TRUE)
    cache <- file.path(output_dir, "source")
    dir.create(cache, showWarnings=FALSE)

    # Version and checksum verified against the official Bioconductor 3.20
    # source PACKAGES index. The data file is independent of package imports.
    version <- "3.14.0"
    expected_md5 <- "efb481b40f689c417e9dbab4a98f71f1"
    url <- paste0(
        "https://bioconductor.org/packages/3.20/data/experiment/src/contrib/",
        "curatedMetagenomicData_", version, ".tar.gz"
    )
    archive <- file.path(cache, basename(url))
    if (!file.exists(archive)) {
        partial <- tempfile(".cmd-download-", tmpdir=cache, fileext=".tar.gz")
        on.exit(unlink(partial), add=TRUE)
        download.file(url, partial, mode="wb")
        if (!identical(unname(tools::md5sum(partial)), expected_md5))
            stop("Downloaded source checksum does not match the official index")
        if (!file.rename(partial, archive)) stop("Cannot publish source archive")
    }
    if (!identical(unname(tools::md5sum(archive)), expected_md5))
        stop("Cached source checksum mismatch; preserve it and choose a new output directory")

    temporary <- tempfile(".cmd-export-", tmpdir=output_dir)
    dir.create(temporary)
    on.exit(unlink(temporary, recursive=TRUE), add=TRUE)
    members <- c("curatedMetagenomicData/data/sampleMetadata.rda",
                 "curatedMetagenomicData/DESCRIPTION")
    if (!all(members %in% untar(archive, list=TRUE)))
        stop("Official source archive is missing the expected data files")
    untar(archive, files=members, exdir=temporary)
    description <- read.dcf(file.path(temporary, members[[2L]]))
    if (!identical(unname(description[1L, "Version"]), version))
        stop("Source version mismatch")
    data_env <- new.env(parent=baseenv())
    objects <- load(file.path(temporary, members[[1L]]), envir=data_env)
    if (!"sampleMetadata" %in% objects) stop("Missing sampleMetadata object")
    metadata <- get("sampleMetadata", envir=data_env, inherits=FALSE)
    required <- c("sample_id", "subject_id", "study_name", "body_site",
                  "study_condition", "NCBI_accession")
    if (!is.data.frame(metadata) || !nrow(metadata) || !all(required %in% names(metadata)))
        stop("Unexpected sampleMetadata data structure")

    filename <- "sample_metadata.tsv"
    staged <- file.path(temporary, filename)
    # Quoting preserves tabs/newlines in free-text metadata fields.
    write.table(metadata, staged, sep="\t", quote=TRUE, row.names=FALSE,
                na="", fileEncoding="UTF-8")
    check <- read.delim(staged, check.names=FALSE, colClasses="character",
                        na.strings="", fileEncoding="UTF-8", comment.char="")
    if (!identical(dim(check), dim(metadata)) || !identical(names(check), names(metadata))
        || !identical(check$sample_id, as.character(metadata$sample_id)))
        stop("Exported metadata did not pass the round-trip check")
    writeLines(version, file.path(temporary, "package_version.txt"))
    source <- data.frame(
        package="curatedMetagenomicData", source_version=version,
        bioconductor_release="3.20", source_url=url, archive_md5=expected_md5,
        metadata_md5=unname(tools::md5sum(staged)),
        rows=nrow(metadata), columns=ncol(metadata),
        extraction_method="base_R_load_from_official_source_data_only",
        stringsAsFactors=FALSE
    )
    write.table(source, file.path(temporary, "metadata_source.tsv"), sep="\t",
                quote=TRUE, row.names=FALSE, na="", fileEncoding="UTF-8")
    outputs <- c(filename, "package_version.txt", "metadata_source.tsv")
    # Validate every destination before publishing any output. Different existing
    # snapshots are never silently overwritten.
    for (name in outputs) {
        target <- file.path(output_dir, name)
        if (file.exists(target) && !identical(unname(tools::md5sum(target)),
                                               unname(tools::md5sum(file.path(temporary, name)))))
            stop(paste("Existing output differs; use --output-dir with a new directory:", name))
    }
    for (name in outputs) {
        target <- file.path(output_dir, name)
        if (!file.exists(target) && !file.rename(file.path(temporary, name), target))
            stop(paste("Cannot publish", name))
        Sys.chmod(target, mode="0600")
    }
    cat("Metadata exported and verified:", nrow(metadata), "samples x", ncol(metadata), "fields\n")
    cat("Source package:", version, "(source data only; package not installed)\n")
    cat("Output:", file.path(output_dir, filename), "\n")
    cat("This is a complete metadata snapshot containing healthy and disease samples; it is not a healthy cohort.\n")
}

tryCatch(main(), error=function(error) {
    message("Metadata export failed: ", conditionMessage(error))
    quit(status=1L)
})
