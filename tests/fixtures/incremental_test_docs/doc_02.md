# Incremental Processing Guide

Incremental ingestion processes only new, updated, or deleted documents between pipeline runs.
By hashing document content and tracking file timestamps, redundant extraction steps are skipped.
Soft deletion ensures that removed documents are cleanly purged from downstream vector indexes.
