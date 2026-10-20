# Tasks

## 1. Reproduce and specify

- [x] 1.1 [backend] Inspect issue #306, current adapter/validator/loader behavior, and existing specs.
- [x] 1.2 [backend] Write proposal, design, and spec delta; request review before implementation.
- [x] 1.3 [backend] Strictly validate the OpenSpec change and record the result (OpenSpec 1.14.3: valid).
- [x] 1.4 [backend] Record independent review of proposal and spec delta before production-code edits; no maintainer
  approval is claimed.
- [x] 1.5 [backend] Use `test_package_adapter_installed.py` to capture the pre-fix import failure for a package with no
  entry points and the wrong-class result for two operators in a real installed package.

## 2. Implement and verify

- [x] 2.1 [backend] Correct module-inspection path and resolve the named operator consistently in validation and loading.
- [x] 2.2 [backend] Update `TestValidateModule.test_multiple_operator_classes_warn_and_use_the_first` after establishing
  the new named-class behavior; test multi-class identity and valid locally defined entry points.
- [x] 2.3 [backend] Test invalid/missing/imported/abstract classes, error handling, named plain module paths,
  filesystem/S3 metadata, and empty-name compatibility.
- [x] 2.4 [backend] Run focused (114 passed) and unshimmed operator-loader (79 passed) suites, changed-file
  lint/format and narrow type checks, and strict OpenSpec validation. Full repository suites and pre-commit remain
  unverified.
- [x] 2.5 [backend] Review the complete diff, fix findings, and prepare the PR description without publishing.
