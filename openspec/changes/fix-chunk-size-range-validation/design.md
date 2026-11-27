# Design

## Context

`ChunkerPanelBody` renders chunk size with a Carbon `NumberInput` and static `min`/`max`, but supplies only the required-parameter error text, so an out-of-range value shows no message. Save-button state is computed in two places from `hasAnyRequiredParamMissing`: `CommonPropertiesWrapper.handlePropertyListener` (fires on every property change, including `chunk_type`) and `CommonPropertiesPanel.updateSaveButton` (on mount). Range display and checks already exist as private helpers in `ProviderFieldsForm` (#137). Operator metadata exposes a single chunk size range (100-5000, the union across types), so per-type ranges must come from the frontend.

## Goals / Non-Goals

Goals: inline message, Save gating, revalidation on chunk type change, single source of truth for ranges, reuse of the existing range helper and localized message.
Non-goals: backend validation (#449), other operator panels, overlap validation.

## Component hierarchy

```
CommonPropertiesWrapper (Elyra CommonProperties, propertyListener -> Save state)
  CommonPropertiesPanel (mount-time Save state)
    ChunkerPanelBody
      Dropdown        chunk_type
      NumberInput     chunk_size   <- invalid + invalidText (range message)
```

## Decisions

- Add `CHUNK_SIZE_RANGE` (`simple: 500-5000`, `hybrid: 100-2048`) to `Chunker/constants.ts`. The `NumberInput` `min`/`max` and the validation both read from it, replacing hard-coded literals.
- Add `Chunker/chunkSizeValidation.ts` with `getChunkSizeRange(chunkType)` (undefined for Semantic) and `isChunkSizeOutOfRange(...)`. These are pure functions usable by the panel and by Save gating.
- Extract `isOutOfRange` and `buildRangeText` from `ProviderFieldsForm.tsx` into `shared/rangeValidation.ts`, keeping the existing message IDs so `messages_en.json` is unchanged. The only change to `ProviderFieldsForm` is importing them.
- Reuse the `rangeAllowed` message as the inline text, consistent with provider fields.
- Add `PropertiesPanel/saveValidation.ts` exposing `shouldDisableSave(...)`. It combines `hasAnyRequiredParamMissing` with a small per-operator map of validators (currently only `chunker`). Both `CommonPropertiesWrapper` and `CommonPropertiesPanel` call it, so the two code paths cannot diverge.
- Revalidation on chunk type change is inherent: the panel derives validity from the current `chunk_type` and `chunk_size` on every render, and Elyra's property listener fires on `chunk_type` changes, which re-runs `shouldDisableSave`.
- The chunk size `onChange` guard changes from `n > 0` to "non-empty and finite", so 0 or a negative number is stored and flagged instead of being silently ignored (which previously left a stale valid value and an enabled Save button). Empty input is still ignored, as before.

## Risks / Trade-offs

- Frontend range constants duplicate backend constants (`CHUNK_MIN_SIZE`, `CHUNK_MAX_SIZE`, `DOCLING_CHUNK_SIZE_MIN`). They already existed as literals in the panel; centralizing them reduces drift. Per-type ranges are not exposed by metadata, so this is the lowest-risk option.
- Existing flows containing an out-of-range chunk size will now show an error and block Save until corrected. That matches run-time behavior.

## Migration Plan

No data migration or dependency changes. Rollback is a revert of the frontend change.
