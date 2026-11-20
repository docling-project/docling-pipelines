# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Utility functions for data access and parquet table I/O in docpipe."""

import re

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.utils.infrastructure.filesystem import get_data_path


class DataAccessConstants:
    """Dataaccessconstants."""

    MEMORY = "memory"
    LOCAL = "local"
    COS = "cos"
    S3 = "s3"
    FLIGHT = "flight"
    DATA_STORAGE_TYPE = "data_storage_type"


# Key is storage type and value is config key
data_access_config_key_map: dict[str, str] = {
    DataAccessConstants.MEMORY: "data_config",
    DataAccessConstants.LOCAL: "data_local_config",
    DataAccessConstants.COS: "data_config",
    DataAccessConstants.S3: "data_config",
    DataAccessConstants.FLIGHT: "data_flight_config",
}


class DataAccessUtils:
    """Utility class for data access operations in docpipe."""

    @staticmethod
    def add_node_name_to_output_folder(*, params: dict, node_name):
        """Add node name to output folder."""
        node_name = re.sub(r"\W+", "_", node_name)
        storage_type = params.get(DataAccessConstants.DATA_STORAGE_TYPE)
        if not storage_type:
            return

        config_key = data_access_config_key_map.get(storage_type)
        if not config_key:
            return

        config = params.get(config_key)
        if config:
            output_folder = config.get(DocpipeConstants.OUTPUT_FOLDER)

            # Check if batch_num is present in params
            batch_num = params.get(DocpipeConstants.BATCH_NUM)
            if batch_num is not None:
                # Add batch number to path: <output_folder>/<node_name>/<batch_num>
                config[DocpipeConstants.OUTPUT_FOLDER] = f"{output_folder}/{node_name}/{batch_num}"
            else:
                config[DocpipeConstants.OUTPUT_FOLDER] = f"{output_folder}/{node_name}"

            config["cache"] = True

    @staticmethod
    def add_intermediate_storage_config(config: dict, job_id: str, job_run_id: str):
        """Based on the data_storage_type, the corresponding storage configuration is added to the config."""
        if config.get(DataAccessConstants.DATA_STORAGE_TYPE, "") == DataAccessConstants.LOCAL:
            DataAccessUtils.add_data_local_config_for_cpd(config=config, job_id=job_id, job_run_id=job_run_id)
        else:  # storage type is memory
            if "data_local_config" in config:
                config["data_local_config"] = None
            config["data_config"] = {
                "da_class": "data_processing.data_access.DataAccessMemory",
                "output_folder": "",
            }

    @staticmethod
    def default_intermediate_output_folder(*, job_id: str, job_run_id: str) -> str:
        """Return the folder holding the intermediate node outputs of a job run when no output folder is configured."""
        return f"{get_data_path()}/{job_id}/{job_run_id}/data"

    @staticmethod
    def add_data_local_config_for_cpd(config: dict, job_id: str, job_run_id: str):
        """Add data local config for cpd."""
        local_config = config.get("data_local_config", {})
        config["data_config"] = None
        if not local_config or not local_config.get("output_folder"):
            output_folder = DataAccessUtils.default_intermediate_output_folder(job_id=job_id, job_run_id=job_run_id)
            config["data_local_config"] = {
                "input_folder": "UNUSED",
                "output_folder": output_folder,
                "da_class": "docpipe.core.data_access.DocpipeDataAccessLocal",
            }
        else:
            local_config["input_folder"] = "UNUSED"
            # Ensure custom class is used
            local_config["da_class"] = "docpipe.core.data_access.DocpipeDataAccessLocal"
