"""
DocpipeFlowManager Example 5: Jupyter Notebook Usage Pattern

This example demonstrates the typical pattern for using DocpipeFlowManager
in a Jupyter notebook environment.

Prerequisites:
- Virtual environment activated: source .venv/bin/activate
- PYTHONPATH set: export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
- External services such as Ollama or OpenSearch are needed only by notebook flows that use them;
  this script only prints the usage pattern

Setup (from repository root):
    python3.12 -m venv .venv
    source .venv/bin/activate
    uv sync --extra dev
    export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

Run:
    source .venv/bin/activate
    export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
    python examples/docpipe_flow_manager/05_notebook_usage.py
"""


def main():
    """
    Jupyter Notebook Usage Pattern

    This example shows the typical pattern for using DocpipeFlowManager
    in a Jupyter notebook environment.
    """
    print("\n" + "=" * 70)
    print("Example 5: Jupyter Notebook Usage Pattern")
    print("=" * 70)

    print("""
# Typical Jupyter Notebook Usage:

IMPORTANT: Before starting Jupyter, activate the virtual environment:
    source .venv/bin/activate
    export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"
    jupyter notebook

```python
# Cell 1: Import and setup
import sys
from pathlib import Path

# Add src to path for local development
src_path = Path.cwd().parent.parent / "src"
sys.path.insert(0, str(src_path))
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

# Cell 2: List available operators
print(DocpipeFlowManager.list_operators())

# Cell 3: Define or load flow
flow_file = "path/to/your/flow.json"

# Or define inline:
flow_def = {
    "flow_name": "My Notebook Flow",
    "flow": [
        # ... operator definitions
    ]
}

# Cell 4: Create flow manager
manager = DocpipeFlowManager(
    flow_file=flow_file  # or flow_def=flow_def
)

# Cell 5: Check metadata
metadata = manager.get_execution_metadata()
print(f"Flow: {metadata['flow_name']}")
print(f"Operators: {metadata['num_operators']}")

# Cell 6: Execute
manager.execute()

# Cell 7: Check execution status
if manager.orchestrator:
    job_stats_service = manager.orchestrator.job_stats_service
    if job_stats_service:
        job_stats = job_stats_service.get_job_run_stats(job_run_id=manager.job_run_id)
        if job_stats:
            print(f"Execution Status: {job_stats.status}")
            print(f"Job Run ID: {manager.job_run_id}")
```

Key Benefits for Notebooks:
- Clean, simple API
- Step-by-step execution
- Easy to inspect metadata
- Good error messages
- No need to manage CLI arguments

Note: The execute() method returns None by design.
Results are tracked through the job stats service.
    """)


if __name__ == "__main__":
    main()
