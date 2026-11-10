# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Process isolation for untrusted custom operators (design D12, task D.3).

Keep this package ``__init__`` free of imports: the worker process starts by importing
``docpipe.core.orchestration.operator_loader.isolation.worker_main``, and everything imported here is imported there.
"""
