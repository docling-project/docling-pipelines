# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Checks for locally generated file-format fixtures."""

from pathlib import Path
from zipfile import ZipFile, is_zipfile

import olefile
import pytest

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "file_formats"
EXTENSIONS = "csv epub eml msg tex latex adoc asciidoc asc vtt htm xhtml mhtml mht markdown text qmd rmd pptm xlsm xltx xltm mkv webm".split()


@pytest.mark.parametrize("extension", EXTENSIONS)
def test_fixture_is_present_and_has_no_embedded_active_content(extension):
    path = FIXTURES / f"sample.{extension}"
    assert path.is_file()
    if is_zipfile(path):
        with ZipFile(path) as archive:
            names = archive.namelist()
            assert not any(
                item in name.lower()
                for name in names
                for item in ("vbaproject", "embeddings/", "externallinks/", "activex/")
            )
            assert all(b'TargetMode="External"' not in archive.read(name) for name in names if name.endswith(".rels"))
    if extension == "msg":
        with olefile.OleFileIO(path) as message:
            assert all("attach" not in part.lower() for stream in message.listdir() for part in stream)
