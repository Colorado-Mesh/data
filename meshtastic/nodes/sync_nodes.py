import argparse
import json
import os
from datetime import datetime
from typing import Optional

import objectrest
from pydantic import BaseModel, Field

from coloradomesh.colorado import COLORADO
from coloradomesh.meshtastic.models.general import Node, NodeRole

MESHMAP_URL = "https://meshmap.net/nodes.json"  # All Meshtastic devices globally
LIAMCOTTLE_MESHTASTIC_URL = "https://meshtastic.liamcottle.net/api/v1/nodes"  # All Meshtastic devices globally
CM_MESHVIEW_URL = "https://map.meshtastic.coloradomesh.org/api/nodes?days_active=3"  # All ACTIVE Meshtastic devices heard on the msh/US/CO topic
MALLA_US_URL = "https://mshus.meshmonitoring.com/api/locations"  # All Meshtastic devices in US reporting location
CM_POTATOMESH_URL = "https://potato.meshtastic.coloradomesh.org/api/nodes"  # All Meshtastic devices heard by local observers

_COLORADO = COLORADO

COLORADO_MSH_TOPIC = "msh/US/CO"

COLORADO_LAT_MIN = 36
COLORADO_LAT_MAX = 41.5
COLORADO_LON_MIN = -110
COLORADO_LON_MAX = -101


class _BaseDataSourceNode(BaseModel):
    def _node_is_in_colorado_precision(self) -> bool:
        if not all([self.filter_latitude, self.filter_longitude]):
            return False

        return _COLORADO.coordinates_within_borders(latitude=self.filter_latitude, longitude=self.filter_longitude)

    def node_is_in_boundary(self, lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> bool:
        return (
                all([self.filter_latitude, self.filter_longitude]) and
                all([(lat_min <= self.filter_latitude <= lat_max), (lon_min <= self.filter_longitude <= lon_max)])
        )

    @classmethod
    def filter_to_colorado(cls, nodes: list['_BaseDataSourceNode'], data_source: str) -> list['_BaseDataSourceNode']:
        print(f"Filtering {len(nodes)} nodes from {data_source} to those within Colorado")

        print(
            f"Applying pre-filter to nodes with lat between {COLORADO_LAT_MIN} and {COLORADO_LAT_MAX} and lon between {COLORADO_LON_MIN} and {COLORADO_LON_MAX}")

        prefiltered_nodes: list['_BaseDataSourceNode'] = [
            node for node in nodes if node.node_is_in_boundary(
                lat_min=COLORADO_LAT_MIN,
                lat_max=COLORADO_LAT_MAX,
                lon_min=COLORADO_LON_MIN,
                lon_max=COLORADO_LON_MAX,
            )
        ]

        print(f"Checking remaining {len(prefiltered_nodes)} nodes for exact Colorado presence")

        filtered_nodes: list['_BaseDataSourceNode'] = [
            node for node in prefiltered_nodes if node._node_is_in_colorado_precision()
        ]

        print(f"Found {len(filtered_nodes)} nodes in Colorado via {data_source}")
        return filtered_nodes

    @property
    def filter_latitude(self) -> Optional[float]:
        raise NotImplementedError

    @property
    def filter_longitude(self) -> Optional[float]:
        raise NotImplementedError


### MeshMap-specific models for parsing API responses
class MeshMapNode(_BaseDataSourceNode):
    id: Optional[int] = Field(alias="id", default=None)
    long_name: str = Field(alias="longName")
    short_name: str = Field(alias="shortName")
    hardware_model: Optional[str] = Field(alias="hwModel", default=None)
    role: Optional[str] = Field(alias="role", default=None)
    latitude: Optional[float] = Field(alias="latitude", default=None)
    longitude: Optional[float] = Field(alias="longitude", default=None)
    altitude: Optional[float] = Field(alias="altitude", default=None)
    precision: Optional[int] = Field(alias="precision", default=None)
    seen_by: Optional[dict] = Field(alias="seenBy", default=None)

    # This is unused because it would be too intensive to iterate through all global nodes to check there seenBy lists
    @property
    def seen_by_colorado_mqtt_topic(self) -> bool:
        if not self.seen_by:
            return False

        for key, value in self.seen_by.items():
            if key.startswith(COLORADO_MSH_TOPIC):
                return True

        return False

    @property
    def real_latitude(self) -> Optional[float]:
        # Move decimal seven digits to the left
        return (float(self.latitude) / 10_000_000) if self.latitude else None

    @property
    def real_longitude(self) -> Optional[float]:
        return (float(self.longitude) / 10_000_000) if self.longitude else None

    @property
    def filter_latitude(self) -> Optional[float]:
        return self.real_latitude

    @property
    def filter_longitude(self) -> Optional[float]:
        return self.real_longitude

    @property
    def node_role(self) -> NodeRole:
        return NodeRole.from_name(name=self.role) if self.role is not None else NodeRole.UNKNOWN

    def to_node(self) -> Node:
        return Node(
            id=str(self.id) if self.id else None,
            long_name=self.long_name,
            short_name=self.short_name,
            hardware_model=self.hardware_model,
            role=self.node_role,
            latitude=self.real_latitude,
            longitude=self.real_longitude,
            altitude=self.altitude,
            precision=self.precision
        )


def _get_meshmap_nodes() -> list[MeshMapNode]:
    """
    Fetch all nodes from the MeshMap API.
    Filters nodes to just those with lat/lon inside Colorado borders.
    :rtype: list[MeshMapNode]
    """
    all_nodes_data: dict = objectrest.get_object(url=MESHMAP_URL,  # type: ignore
                                                 model=dict)
    if not all_nodes_data:
        # We don't want to return an empty list, that would effectively erase the previous data snapshot
        # Instead, consider this run failed
        raise Exception(f"Could not load nodes from MeshMap")

    all_nodes: list[MeshMapNode] = [
        MeshMapNode(id=node_id, **node_data) for (node_id, node_data) in all_nodes_data.items()
    ]
    if not all_nodes:
        # We don't want to return an empty list, that would effectively erase the previous data snapshot
        # Instead, consider this run failed
        raise Exception(f"Could not load nodes from MeshMap")

    print(f"Found {len(all_nodes)} nodes from MeshMap")

    return MeshMapNode.filter_to_colorado(nodes=all_nodes, data_source="MeshMap")  # type: ignore


### Liam Cottle Meshtastic Map-specific models for parsing API responses
class LiamCottleMeshtasticNode(_BaseDataSourceNode):
    id: Optional[int] = Field(alias="id", default=None)
    node_id: Optional[int] = Field(alias="node_id", default=None)
    long_name: str = Field(alias="long_name")
    short_name: str = Field(alias="short_name")
    hardware_model: Optional[int] = Field(alias="hardware_model", default=None)
    hardware_model_name: Optional[str] = Field(alias="hardware_model_name", default=None)
    role: Optional[int] = Field(alias="role", default=None)
    role_name: Optional[str] = Field(alias="role_name", default=None)
    latitude: Optional[float] = Field(alias="latitude", default=None)
    longitude: Optional[float] = Field(alias="longitude", default=None)
    altitude: Optional[float] = Field(alias="altitude", default=None)
    position_precision: Optional[int] = Field(alias="position_precision", default=None)
    position_updated_at: Optional[str] = Field(alias="position_updated_at", default=None)
    created_at: Optional[datetime] = Field(alias="created_at", default=None)
    updated_at: Optional[datetime] = Field(alias="updated_at", default=None)
    region_name: Optional[str] = Field(alias="region_name", default=None)
    mqtt_connection_state_updated_at: Optional[datetime] = Field(alias="mqtt_connection_state_updated_at", default=None)

    # Plus a bunch more irrelevant data

    @property
    def real_latitude(self) -> Optional[float]:
        # Move decimal seven digits to the left
        return (float(self.latitude) / 10_000_000) if self.latitude else None

    @property
    def real_longitude(self) -> Optional[float]:
        return (float(self.longitude) / 10_000_000) if self.longitude else None

    @property
    def node_role(self) -> NodeRole:
        return NodeRole.from_int(self.role) if self.role is not None else NodeRole.UNKNOWN

    @property
    def filter_latitude(self) -> Optional[float]:
        return self.real_latitude

    @property
    def filter_longitude(self) -> Optional[float]:
        return self.real_longitude

    def to_node(self) -> Node:
        return Node(
            id=str(self.id) if self.id else None,
            long_name=self.long_name,
            short_name=self.short_name,
            hardware_model=self.hardware_model_name,
            role=self.node_role,
            latitude=self.real_latitude,
            longitude=self.real_longitude,
            altitude=self.altitude,
            precision=self.position_precision,
        )


def _get_liam_cottle_nodes() -> list[LiamCottleMeshtasticNode]:
    """
    Fetch all nodes from the Liam Cottle Meshtastic Map API.
    Filters nodes to just those with lat/lon inside Colorado borders.
    :rtype: list[LiamCottleMeshtasticNode]
    """
    all_nodes: list[LiamCottleMeshtasticNode] = objectrest.get_object(url=LIAMCOTTLE_MESHTASTIC_URL,  # type: ignore
                                                                      model=LiamCottleMeshtasticNode,
                                                                      extract_list=True,
                                                                      sub_keys=["nodes"]
                                                                      )
    if not all_nodes:
        # We don't want to return an empty list, that would effectively erase the previous data snapshot
        # Instead, consider this run failed
        raise Exception(f"Could not load nodes from Liam Cottle's Meshtastic Map")

    print(f"Found {len(all_nodes)} nodes from Liam Cottle's Meshtastic Map")

    return LiamCottleMeshtasticNode.filter_to_colorado(nodes=all_nodes,  # type: ignore
                                                       data_source="Liam Cottle's Meshtastic Map")


### MeshView-specific models for parsing API responses
class MeshViewNode(_BaseDataSourceNode):
    id: str = Field(alias="id")
    node_id: int = Field(alias="node_id")
    long_name: str = Field(alias="long_name")
    short_name: str = Field(alias="short_name")
    hardware_model: Optional[str] = Field(alias="hw_model", default=None)
    firmware: Optional[str] = Field(alias="firmware", default=None)
    role: str = Field(alias="role")
    latitude: Optional[float] = Field(alias="last_lat", default=None)
    longitude: Optional[float] = Field(alias="last_long", default=None)
    first_seen: int = Field(alias="first_seen_us")  # UNIX timestamp
    last_seen: int = Field(alias="last_seen_us")  # UNIX timestamp

    @property
    def real_latitude(self) -> Optional[float]:
        # Move decimal seven digits to the left
        return (float(self.latitude) / 10_000_000) if self.latitude else None

    @property
    def real_longitude(self) -> Optional[float]:
        return (float(self.longitude) / 10_000_000) if self.longitude else None

    @property
    def filter_latitude(self) -> Optional[float]:
        return self.real_latitude

    @property
    def filter_longitude(self) -> Optional[float]:
        return self.real_longitude

    @property
    def node_role(self) -> NodeRole:
        return NodeRole.from_name(name=self.role) if self.role is not None else NodeRole.UNKNOWN

    def to_node(self) -> Node:
        return Node(
            id=str(self.node_id),
            long_name=self.long_name,
            short_name=self.short_name,
            hardware_model=self.hardware_model,
            role=self.node_role,
            latitude=self.real_latitude,
            longitude=self.real_longitude,
            altitude=None,
            precision=None,
        )


def _get_meshview_nodes() -> list[MeshViewNode]:
    """
    Fetch all nodes from the MeshView API.
    :rtype: list[MeshViewNode]
    """
    all_nodes: list[MeshViewNode] = objectrest.get_object(url=CM_MESHVIEW_URL,  # type: ignore
                                                          model=MeshViewNode,
                                                          extract_list=True,
                                                          sub_keys=["nodes"]
                                                          )

    if not all_nodes:
        # We don't want to return an empty list, that would effectively erase the previous data snapshot
        # Instead, consider this run failed
        raise Exception(f"Could not load nodes from MeshView")

    print(f"Found {len(all_nodes)} nodes in Colorado via MeshView")
    return all_nodes


### MallaUS-specific models for parsing API responses
class MallaUSNode(_BaseDataSourceNode):
    hex_id: str = Field(alias="hex_id")
    node_id: int = Field(alias="node_id")
    long_name: Optional[str] = Field(alias="long_name", default=None)
    short_name: Optional[str] = Field(alias="short_name", default=None)
    hardware_model: Optional[str] = Field(alias="hw_model", default=None)
    latitude: Optional[float] = Field(alias="latitude", default=None)
    longitude: Optional[float] = Field(alias="longitude", default=None)
    altitude: Optional[float] = Field(alias="altitude", default=None)
    precision_meters: Optional[float] = Field(alias="precision_meters", default=None)
    role: Optional[str] = Field(alias="role", default=None)
    last_seen: float = Field(alias="timestamp")  # UNIX timestamp

    # Plus a bunch more irrelevant data

    @property
    def filter_latitude(self) -> Optional[float]:
        return self.latitude

    @property
    def filter_longitude(self) -> Optional[float]:
        return self.longitude

    @property
    def node_role(self) -> NodeRole:
        return NodeRole.from_name(name=self.role) if self.role is not None else NodeRole.UNKNOWN

    def to_node(self) -> Node:
        return Node(
            id=str(self.node_id),
            long_name=self.long_name,  # type: ignore (will be there)
            short_name=self.short_name,  # type: ignore (will be there)
            hardware_model=self.hardware_model,
            role=self.node_role,
            latitude=self.latitude,
            longitude=self.longitude,
            altitude=self.altitude,
            precision=int(self.precision_meters) if self.precision_meters is not None else None,
        )


def _get_malla_us_nodes() -> list[MallaUSNode]:
    """
    Fetch all nodes from the MallaUS API.
    :rtype: list[MallaUSNode]
    """
    all_nodes: list[MallaUSNode] = objectrest.get_object(url=MALLA_US_URL,  # type: ignore
                                                         model=MallaUSNode,
                                                         extract_list=True,
                                                         sub_keys=["locations"]
                                                         )

    if not all_nodes:
        # We don't want to return an empty list, that would effectively erase the previous data snapshot
        # Instead, consider this run failed
        raise Exception(f"Could not load nodes from Malla US")

    print(f"Found {len(all_nodes)} nodes in Colorado via Malla US")

    filtered_nodes: list[MallaUSNode] = MallaUSNode.filter_to_colorado(nodes=all_nodes, # type: ignore
                                                                       data_source="Malla US")

    # Additional filter, only include nodes with long names
    complete_nodes: list[MallaUSNode] = [
        node for node in filtered_nodes if node.long_name is not None
    ]
    print(f"Found {len(complete_nodes)} valid nodes in Colorado via Malla US")

    return complete_nodes


### PotatoMesh-specific models for parsing API responses
class PotatoMeshNode(_BaseDataSourceNode):
    node_id: str = Field(alias="node_id")
    long_name: Optional[str] = Field(alias="long_name", default=None)
    short_name: Optional[str] = Field(alias="short_name", default=None)
    role: Optional[str] = Field(alias="role", default=None)
    snr: Optional[float] = Field(alias="snr", default=None)
    last_heard: Optional[float] = Field(alias="last_heard", default=None)  # UNIX timestamp
    first_heard: Optional[float] = Field(alias="first_heard", default=None)  # UNIX timestamp
    position_time: Optional[float] = Field(alias="position_time", default=None)  # UNIX timestamp
    location_source: Optional[str] = Field(alias="location_source", default=None)
    precision_bits: Optional[int] = Field(alias="precision_bits", default=None)
    latitude: Optional[float] = Field(alias="latitude", default=None)
    longitude: Optional[float] = Field(alias="longitude", default=None)
    altitude: Optional[float] = Field(alias="altitude", default=None)
    lora_frequency: Optional[float] = Field(alias="lora_freq", default=None)
    modem_preset: Optional[str] = Field(alias="modem_preset", default=None)
    protocol: Optional[str] = Field(alias="protocol", default=None)
    last_seen_iso: Optional[str] = Field(alias="last_seen_iso", default=None)

    @property
    def filter_latitude(self) -> Optional[float]:
        return self.latitude

    @property
    def filter_longitude(self) -> Optional[float]:
        return self.longitude

    @property
    def node_role(self) -> NodeRole:
        return NodeRole.from_name(name=self.role) if self.role is not None else NodeRole.UNKNOWN

    def to_node(self) -> Node:
        return Node(
            id=self.node_id,
            long_name=self.long_name,  # type: ignore (will be there)
            short_name=self.short_name,  # type: ignore (will be there)
            hardware_model=None,
            role=self.node_role,
            latitude=self.latitude,
            longitude=self.longitude,
            altitude=self.altitude,
            precision=None,  # We don't know the meter measurement
        )


def _get_potatomesh_nodes() -> list[PotatoMeshNode]:
    """
    Fetch all nodes from the Colorado Mesh PotatoMesh API.
    :rtype: list[PotatoMeshNode]
    """
    all_nodes: list[PotatoMeshNode] = objectrest.get_object(url=CM_POTATOMESH_URL,  # type: ignore
                                                            model=PotatoMeshNode,
                                                            extract_list=True,
                                                            )

    if not all_nodes:
        # We don't want to return an empty list, that would effectively erase the previous data snapshot
        # Instead, consider this run failed
        raise Exception(f"Could not load nodes from PotatoMesh")

    print(f"Found {len(all_nodes)} nodes in Colorado via PotatoMesh")

    # Additional filter, only include nodes with long names
    valid_nodes: list[PotatoMeshNode] = [
        node for node in all_nodes if node.long_name is not None
    ]
    print(f"Found {len(valid_nodes)} valid nodes in Colorado via PotatoMesh")

    return valid_nodes


def get_colorado_nodes() -> list[Node]:
    """
    Get all nodes in Colorado.
    :return: A list of Node objects representing all nodes in Colorado.
    :rtype: list[Node]
    """
    liam_cottle_nodes: list[LiamCottleMeshtasticNode] = _get_liam_cottle_nodes()
    liam_cottle_nodes_converted: list[Node] = [
        node.to_node() for node in liam_cottle_nodes
    ]

    meshmap_nodes: list[MeshMapNode] = _get_meshmap_nodes()
    meshmap_nodes_converted: list[Node] = [
        node.to_node() for node in meshmap_nodes
    ]

    meshview_nodes: list[MeshViewNode] = _get_meshview_nodes()
    meshview_nodes_converted: list[Node] = [
        node.to_node() for node in meshview_nodes
    ]

    """No longer available
    malla_us_nodes: list[MallaUSNode] = _get_malla_us_nodes()
    malla_us_nodes_converted: list[Node] = [
        node.to_node() for node in malla_us_nodes
    ]
    """

    potatomesh_nodes: list[PotatoMeshNode] = _get_potatomesh_nodes()
    potatomesh_nodes_converted: list[Node] = [
        node.to_node() for node in potatomesh_nodes
    ]

    # Remove duplicates by whole ID
    # Yes, it's possible two nodes, each on different maps, happen to have the same ID, but that's highly unlikely
    # Defer to the newer node if there is a conflict (list built from least-to-most trustworthy)
    unique_nodes_dict: dict[str, Node] = {}
    for node in (
            potatomesh_nodes_converted +
            meshview_nodes_converted +
            meshmap_nodes_converted +
            liam_cottle_nodes_converted
    ):
        node_id = str(node.id)

        unique_nodes_dict[node_id] = node

    return list(unique_nodes_dict.values())


def _read_nodes_from_file(file_path: str) -> list[Node]:
    nodes = []
    if not os.path.exists(file_path):
        return nodes

    with open(file_path, "r", encoding="utf-8") as f:
        _data = json.load(f)
        for item in _data:
            nodes.append(
                Node(**item)
            )
    return nodes


def _filter_diff_nodes(existing_nodes: list[Node], new_nodes: list[Node]) -> tuple[list[Node], list[Node], list[Node]]:
    """
    Filter nodes into three categories:
    1) New nodes that are in new_nodes but not in existing_nodes
    2) Duplicate nodes that are in both existing_nodes and new_nodes
    3) Missing nodes that are in existing_nodes and not in new_nodes (potentially removed nodes)
    :param existing_nodes: The list of existing nodes to compare against.
    :param new_nodes: The list of new nodes to compare with existing nodes.
    :return: A tuple containing three lists: (new_nodes_list, duplicate_nodes_list, missing_nodes_list)
    """
    all_nodes = {}

    existing_node_hash_map = {}
    new_node_hash_map = {}

    # Loop through the "existing" nodes to build a map of hashes of their identifiers
    # and store all nodes in a combined map for easy lookup
    for node in existing_nodes:
        _hash = node.to_human_hash()
        existing_node_hash_map[_hash] = _hash
        all_nodes[_hash] = node

    # Loop through the "new" nodes to build a map of hashes of their identifiers
    # and store all nodes in a combined map for easy lookup
    for node in new_nodes:
        _hash = node.to_human_hash()
        new_node_hash_map[_hash] = _hash
        all_nodes[_hash] = node

    # Prepare sets
    existing_nodes_set = set(existing_node_hash_map.items())
    new_nodes_set = set(new_node_hash_map.items())

    true_new_nodes = new_nodes_set - existing_nodes_set
    duplicate_nodes = new_nodes_set & existing_nodes_set
    missing_nodes = existing_nodes_set - new_nodes_set

    # Look up the actual Node objects for each category based on the hashes and return them as lists
    return (
        list(all_nodes[_hash] for _hash, _ in true_new_nodes),
        list(all_nodes[_hash] for _hash, _ in duplicate_nodes),
        list(all_nodes[_hash] for _hash, _ in missing_nodes),
    )


def sync_nodes(storage_file_path: str) -> None:
    print(f"Fetching Colorado nodes...")
    nodes: list[Node] = get_colorado_nodes()
    print(f"Found {len(nodes)} nodes")

    existing_nodes: list[Node] = _read_nodes_from_file(file_path=storage_file_path)
    print(f"Loaded {len(existing_nodes)} known nodes from cache")

    print(f"Coalescing data...")
    new, duplicate, missing = _filter_diff_nodes(existing_nodes=existing_nodes, new_nodes=nodes)
    print(
        f"Found {len(new)} new nodes, {len(duplicate)} duplicate nodes, and {len(missing)} missing nodes compared to cache")

    if new or missing:
        # Write ALL nodes to file
        print("Updating cache with new nodes...")
        with open(storage_file_path, "w", encoding="utf-8") as f:
            f.write(json.dumps([node.to_json() for node in nodes], ensure_ascii=False, indent=2))
        print("Cache updated.")
    else:
        print("No changes detected, cache not updated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cache Meshtastic devices in Colorado.")
    parser.add_argument(
        "--nodes-data-file",
        type=str,
        help="Path to the data file to store repeater information.",
        required=True
    )
    args = parser.parse_args()

    data_file = args.nodes_data_file

    print("Syncing nodes...")
    sync_nodes(storage_file_path=data_file)
