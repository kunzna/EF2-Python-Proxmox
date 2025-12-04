from proxmox_testing_api import ProxmoxClient
import json


# Connection details
host = '20.119.75.42'
user = 'root@pam'
token_name = 'api'
token_value = '2d0c4d99-0a38-4be5-9939-bf971530b928'
verify_ssl = False

# Create and initialize Proxmox client
endpoint = ProxmoxClient(
    host=host,
    user=user,
    token_name=token_name,
    token_value=token_value,
    verify_ssl=verify_ssl
)

# Initialize the ProxmoxAPI connection
endpoint.initialize_proxmoxapi()

# Fetch cluster status
clusterStatusRequest = "cluster/status"
cluster_status_get = endpoint.get_metrics(clusterStatusRequest)
# print(f"Collected cluster level status info")

# Parse the JSON string
cluster_status = json.loads(cluster_status_get)
# print(f"Collected cluster level status info: {cluster_status}")

# Initialize containers
cluster_info = {}
node_info_list = []

# Ensure cluster_status is a list
if isinstance(cluster_status, list):
    cluster_info = {}
    node_info_list = []

    for item in cluster_status:
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "cluster":
                cluster_info = {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "nodes_count": item.get("nodes")
                }
            elif item_type == "node":
                node_info = {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "online": item.get("online"),
                    "local": item.get("local"),
                    "ip": item.get("ip")
                }
                node_info_list.append(node_info)
        else:
            print(f"Unexpected item type: {type(item)} - {item}")
else:
    print(f"cluster_status is not a list. Check the source of the data.")

# Setting cluster dimension variables
cluster_name = cluster_info.get("name")
cluster_id = cluster_info.get("id")

# Determining the number of online nodes vs total nodes in cluster
cluster_node_count = cluster_info.get("nodes_count")
cluster_node_online_count = sum(
    1 for node in node_info_list
    if node['online'] == 1
)

# Define dimensions for the cluster
cluster_dimensions = {
    "cluster": cluster_name,
    "clusterid": cluster_id,
}
# print(f"Collected cluster level dimensions: {cluster_dimensions}")

# Sending to metrics server for cluster
# self.report_metric(
#     "proxmox.cluster.node.count", cluster_node_count, cluster_dimensions
# )
# self.report_metric(
#     "proxmox.cluster.node.online.count", cluster_node_online_count, cluster_dimensions
# )

# print(f"Sent to metrics server for cluster: {cluster_name} with dimensions: {cluster_dimensions}")

# Fetch cluster HA status
clusterHaStatusRequest = "cluster/ha/status/current"
cluster_ha_status_get = endpoint.get_metrics(clusterHaStatusRequest)
# print(f"Collected cluster high availability status info")

# Parse the JSON string
cluster_ha_status = json.loads(cluster_ha_status_get)
# print(f"Collected cluster high availability status info: {cluster_ha_status}")      

# Ensure cluster_ha_status is a list
if isinstance(cluster_ha_status, list):
    cluster_ha_info = {}
    node_info_list = []

    for item in cluster_ha_status:
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "quorum":
                cluster_ha_info = {
                    "id": item.get("id"),
                    "quorate": item.get("quorate"),
                    "status": item.get("status")
                }
                print(f"Cluster HA Info: {cluster_ha_info}")
        else:
            print(f"Unexpected item type: {type(item)} - {item}")
else:
    print(f"cluster_status is not a list. Check the source of the data.")
# Filter for type == "quorum"
# result = next(({"quorate": item["quorate"], "status": item["status"]}
            # for item in cluster_ha_status["data"] if item["type"] == "quorum"), None)