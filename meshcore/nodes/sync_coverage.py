import argparse
import json
from typing import List

import objectrest
from pydantic import BaseModel

MESHMAPPER_COVERAGE_API_URL = "https://meshmapper.net/coverage.php"


class MeshMapperRegionConfig(BaseModel):
    iata: str
    key: str


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cache MeshCore coverage in Colorado.")
    parser.add_argument(
        "--config-file",
        type=str,
        metavar="FILE",
        help="Path to MeshMapper config file.",
        required=True,
    )
    parser.add_argument(
        "--coverage-data-file",
        type=str,
        help="Path to the data file to store coverage information.",
        required=True
    )
    args = parser.parse_args()

    config_file = args.config_file
    data_file = args.coverage_data_file

    print("Loading config...")
    # Should be a JSON file with an array of MeshMapperRegionConfig objects
    region_configs: List[MeshMapperRegionConfig] = []
    with open(config_file, "r") as f:
        config = json.load(f)
        for region_config in config:
            region_configs.append(MeshMapperRegionConfig(**region_config))

    print(f"Loaded {len(region_configs)} regions from config file")

    all_data: List[dict] = []
    for region_config in region_configs:
        print(f"Caching coverage information for {region_config.iata}...")
        data: dict = objectrest.get_json(
            url=MESHMAPPER_COVERAGE_API_URL,
            params={
                'key': region_config.key,
                #'include': 'repeaters'  # Don't include repeater data, bloats the file
            },
        )
        all_data.append(data)

    # For now, no processing of data here (done by library at runtime), simply cache the API response JSON blobs
    with open(data_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(all_data, ensure_ascii=False, indent=2))
