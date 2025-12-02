from proxmox_api import ProxmoxClient
import json
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from dynatrace_extension import Extension, MetricType
from dynatrace_extension.sdk.communication import divide_into_batches
from dynatrace_extension.sdk.status import StatusValue, Status

try:
    from dynatrace import Dynatrace
except ImportError:
    pass

default_logger = logging.getLogger(__name__)
default_logger.setLevel(logging.INFO)

class ProxmoxExtension():
    def __init__(self):
        self.extension_name = "proxmox_extension"
        self.executor = ThreadPoolExecutor(max_workers=10)
        logger = default_logger
        self.logger = logger
        super().__init__()

    def initialize(self):
        # Connection details
        host = '20.119.75.42'
        user = 'root@pam'
        token_name = 'api'
        token_value = 'a1410e20-5b20-43ff-ba4e-864fb5412001'
        verify_ssl = False

        # Create and initialize Proxmox client
        endpoint = ProxmoxClient(
            host=host,
            user=user,
            token_name=token_name,
            token_value=token_value,
            verify_ssl=verify_ssl
        )

        self.monitor(endpoint)

    def monitor(self, endpoint: dict):        
        endpoint.initialize_proxmoxapi()

        # Fetch cluster status
        clusters_status = json.loads(json.dumps(endpoint.get_cluster_status()))
        # print(f'\nclustersStatusJSON: {clusters_status}')

        cluster_name = next((item["name"] for item in clusters_status if item.get("type") == "cluster"), None)
        cluster_id = next((item["id"] for item in clusters_status if item.get("type") == "cluster"), None)

        # Define dimensions for the cluster
        cluster_dimensions = {
            "cluster": cluster_name,
            "id": cluster_id,
        }
        self.logger.info(f"collected cluster level dimensions: {cluster_dimensions}")
        # print (f'\ncluster_dimensions: {cluster_dimensions}')

        # Fetch node status
        nodes_status = json.loads(json.dumps(endpoint.get_node_status()))
        #print(f'\nnodesStatusJSON: {nodes_status}')

        # Returns the list of nodes in an array
        nodeNamesArray = endpoint.get_node_names(nodes_status)
        #print(f"\nnodeNamesArray: {nodeNamesArray}")

        self.executor.submit(self.collect_nodes, endpoint, nodeNamesArray, cluster_dimensions)
        self.executor.submit(self.collect_storage, endpoint, nodeNamesArray, cluster_dimensions)
        self.executor.submit(self.collect_qemuvm, endpoint, nodeNamesArray, cluster_dimensions)
        self.executor.submit(self.collect_service, endpoint, nodeNamesArray, cluster_dimensions)

    def collect_nodes(self, endpoint, nodeNamesArray, parent_dimensions: dict):

        # Fetch metrics for each node in cluster

        for node_name in nodeNamesArray:
            nodeRequest = "nodes/" + node_name
            nodeMetricsRequest = nodeRequest + "/status"

            # Build node dimensions
            node_dimensions = {
                **parent_dimensions,
                "node": node_name
            }

            # Returns the metrics for each node
            node_metrics = endpoint.get_node_metrics(nodeMetricsRequest)
            #print (f"J\nSON node_metrics: {node_metrics}")

            # Parse the JSON string
            self.logger.info(f"collected node level metrics for node : {node_name}")
            node_data = json.loads(node_metrics)
            #print (f"\nnode_data: {node_data}")

            # Extract CPU info
            cpuinfo_cores = node_data["cpuinfo"]["cores"]
            cpuinfo_sockets = node_data["cpuinfo"]["sockets"]

            # Extract swap metrics
            swap_free = node_data["swap"]["free"]
            swap_total = node_data["swap"]["total"]
            swap_used = node_data["swap"]["used"]

            # Extract rootfs metrics
            rootfs_used = node_data["rootfs"]["used"]
            rootfs_free = node_data["rootfs"]["free"]
            rootfs_total = node_data["rootfs"]["total"]
            rootfs_avail = node_data["rootfs"]["avail"]

            # Extract system metrics
            idle = node_data["idle"]
            cpu = node_data["cpu"]
            uptime = node_data["uptime"]
            wait = node_data["wait"]

            # Extract memory metrics
            memory_used = node_data["memory"]["used"]
            memory_total = node_data["memory"]["total"]
            memory_free = node_data["memory"]["free"]

            # Extract load averages
            loadavg_1m = float(node_data["loadavg"][0])
            loadavg_5m = float(node_data["loadavg"][1])
            loadavg_15m = float(node_data["loadavg"][2])

            # Build dimensions
            node_dimensions = {
                **parent_dimensions,
                "node": node_name
            }

            # Combine metrics and dimensions
            node_metrics_payload = {
                "dimensions": node_dimensions,
                "metrics": {
                    "cpuinfo_cores": cpuinfo_cores,
                    "cpuinfo_sockets": cpuinfo_sockets,
                    "swap_free": swap_free,
                    "swap_total": swap_total,
                    "swap_used": swap_used,
                    "rootfs_used": rootfs_used,
                    "rootfs_free": rootfs_free,
                    "rootfs_total": rootfs_total,
                    "rootfs_avail": rootfs_avail,
                    "idle": idle,
                    "cpu": cpu,
                    "uptime": uptime,
                    "wait": wait,
                    "memory_used": memory_used,
                    "memory_total": memory_total,
                    "memory_free": memory_free,
                    "loadavg_1m": loadavg_1m,
                    "loadavg_5m": loadavg_5m,
                    "loadavg_15m": loadavg_15m
                }
            }

            # Simulate sending to metrics server
            self.logger.info(f"Sending to metrics server: {json.dumps(node_metrics_payload, indent=2)} for node : {node_name} ")
            #print(f"\nSending to metrics server: {json.dumps(node_metrics_payload, indent=2)}")

    def collect_storage(self, endpoint, nodeNamesArray, parent_dimensions: dict):

        # Fetch storage metrics for each node in cluster
 
        # Loop through each node
        for node_name in nodeNamesArray:
            node_storage_metrics = {}
            nodeRequest = "nodes/" + node_name
            nodeStorageRequest = nodeRequest + "/storage"
            
            node_storage_metrics = endpoint.get_node_metrics_2(nodeStorageRequest)

            # Parse the JSON string
            self.logger.info(f"collected node level storage metrics for node : {node_name}")
            storage_data = json.loads(node_storage_metrics)

            #print(f"\nProcessing node: {node_name}")

            # Loop through each storage entry for this node
            for entry in storage_data:
                if entry.get("active") == 1 and entry.get("enabled") == 1:
                    storage_name = entry.get("storage")
                    storage_total = entry.get("total")
                    storage_used = entry.get("used")
                    storage_avail = entry.get("avail")

                    # Build dimensions
                    storage_dimensions = {
                        **parent_dimensions,
                        "node": node_name,
                        "storage": storage_name
                    }

                    # Combine metrics and dimensions
                    storage_metrics_payload = {
                        "dimensions": storage_dimensions,
                        "metrics": {
                            "storage_total": storage_total,
                            "storage_used": storage_used,
                            "storage_avail": storage_avail
                        }
                    }

                    # Simulate sending to metrics server
                    self.logger.info(f"Sending to metrics server: {json.dumps(storage_metrics_payload, indent=2)} for node : {node_name} ")
                    #print(f"\nSending to metrics server: {json.dumps(storage_metrics_payload, indent=2)}")
 
    def collect_qemuvm(self, endpoint, nodeNamesArray, parent_dimensions: dict):

        # Fetch Qemu-VM metrics for each node in cluster
 
        # Loop through each node
        for node_name in nodeNamesArray:
            node_storage_metrics = {}
            nodeRequest = "nodes/" + node_name
            nodeVmRequest = nodeRequest + "/qemu"
            
            node_vm_entries = endpoint.get_node_metrics_2(nodeVmRequest)
            #print (f"\nnode_vm_entries: {node_vm_entries}")

            # Parse the JSON string
            self.logger.info(f"collected node level virtual machine metrics for node : {node_name}")
            vm_entry_data = json.loads(node_vm_entries)

            #print(f"\nProcessing node: {node_name}")

            # Loop through each VM entry for this node to get list of VMs
            for entry in vm_entry_data:
                if entry.get("status") == "running":
                    vm_name = entry.get("name")
                    vm_id = entry.get("vmid")

                    # Build VM dimensions
                    vm_dimensions = {
                        **parent_dimensions,
                        "node": node_name,
                        "vmname": vm_name,
                        "vmid": vm_id
                    }

                    nodeVmSubRequest = nodeVmRequest + "/" + str(vm_id) + "/status/current"
                    node_vm_metrics = endpoint.get_node_metrics_2(nodeVmSubRequest)

                    for vmentry in node_vm_metrics:
                        vm_netout = entry.get("netout")
                        vm_uptime = entry.get("uptime")
                        vm_freemem = entry.get("freemem")
                        vm_maxdisk = entry.get("maxdisk")
                        vm_balloon = entry.get("balloon")
                        vm_diskwrite = entry.get("diskwrite")
                        vm_netin = entry.get("netin")
                        vm_qmpstatus = entry.get("qmpstatus")
                        vm_diskread = entry.get("diskread")
                        vm_mem = entry.get("mem")
                        vm_cpu = entry.get("cpu")
                        vm_cpus = entry.get("cpus")
                        vm_maxmem = entry.get("maxmem")

                    # Combine metrics and dimensions
                    vm_metrics_payload = {
                        "dimensions": vm_dimensions,
                        "metrics": {
                            "vm_netout": vm_netout,
                            "vm_netout": vm_netout,
                            "vm_freemem": vm_freemem,
                            "vm_maxdisk": vm_maxdisk,
                            "vm_balloon": vm_balloon,
                            "vm_diskwrite": vm_diskwrite,
                            "vm_netin": vm_netin,
                            "vm_qmpstatus": vm_qmpstatus,
                            "vm_diskread": vm_diskread,
                            "vm_mem": vm_mem,
                            "vm_cpu": vm_cpu,
                            "vm_cpus": vm_cpus,
                            "vm_maxmem": vm_maxmem
                        }
                    }

                    # Simulate sending to metrics server
                    self.logger.info(f"Sending to metrics server: {json.dumps(vm_metrics_payload, indent=2)} for node: {node_name} for VM: {vm_name}")
                    #print(f"\nSending to metrics server: {json.dumps(vm_metrics_payload, indent=2)}")

    def collect_service(self, endpoint, nodeNamesArray, parent_dimensions: dict):
        # Fetch services status for each node in cluster
        # Loop through each node
        for node_name in nodeNamesArray:
            node_service_metrics = {}
            nodeRequest = "nodes/" + node_name
            nodeserviceRequest = nodeRequest + "/services"
            node_service_metrics = endpoint.get_node_metrics_2(nodeserviceRequest)
 
            # Parse the JSON string
            self.logger.info(f"collected node level service metrics for node : {node_name}")
            service_data = json.loads(node_service_metrics)

            # Loop through each service entry for this node
            for entry in service_data:

                service_name = entry.get("name")
                service_id = entry.get("service")
                service_activestate = entry.get("active-state")
                service_active = entry.get("active")

                if service_activestate == "active": service_activestate = True 
                else: service_activestate = False

                if service_active == "active": service_active = True 
                else: service_active = False                

                # Build dimensions
                service_dimensions = {
                    **parent_dimensions,
                    "node": node_name,
                    "service": service_id,
                    "service_name": service_name
                }

                # Combine metrics and dimensions
                service_metrics_payload = {
                    "dimensions": service_dimensions,
                    "metrics": {
                        "service_active": service_active,
                        "service_activestate": service_activestate
                    }
                }

                # Simulate sending to metrics server
                self.logger.info(f"Sending to metrics server: {json.dumps(service_metrics_payload, indent=2)} for node : {node_name} ")
                print(f"\nSending to metrics server: {json.dumps(service_metrics_payload, indent=2)}")

    def rest_api_metrics(self, mint_lines: list[str]):
        dt = Dynatrace(os.getenv("DT_API_URL"), os.getenv("DT_API_TOKEN"))
        batches = divide_into_batches(mint_lines, 1000000, "\n")
        for batch in batches:
            lines = batch.decode().splitlines()
            print(f"Sending {len(lines)} metrics")
            with open("metrics.txt", "a") as f:
                f.write("\n".join(lines))
            r = dt.metrics.ingest(lines)
            print(r)
        return []

def main():
    extension = ProxmoxExtension()
    extension.initialize()

if __name__ == "__main__":
    main()
