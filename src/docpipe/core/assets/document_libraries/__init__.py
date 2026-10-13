"""Document Library assets management package.

This package implements the Document Library feature using hexagonal architecture.
Document Libraries are collections of Document Sets with aggregate metadata tracking.

Package Structure:
    domain/: Pure Python domain models
    adapters/: Persistence notes (DuckDBAssetRepository[DocumentLibrary] is used directly)
    application/: Business logic and service layer
"""
