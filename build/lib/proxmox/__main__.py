from .proxmox_api import ProxmoxClient
import json
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from dynatrace_extension import Extension, MetricType
from dynatrace_extension.sdk.communication import divide_into_batches
from dynatrace_extension.sdk.status import StatusValue, Status

try:
    from dynatrace import Dynatrace
except ImportError:
    pass

class ProxmoxExtension(Extension):  # Enable for testing with DT Extensions SDK
    def __init__(self):
        self.extension_name = "proxmox_extension_topomapping"
        self.executor = ThreadPoolExecutor(max_workers=10)
        super().__init__()

    def initialize(self, **kwargs):

        endpoints = self.activation_config.get("endpoints")
        for endpoint in endpoints:
            frequency = endpoint.get("frequency", 1)

            user_key = "user"
            host = endpoint.get("host")
            user = endpoint.get(user_key)
            token_name = endpoint.get("token_name")
            token_value = endpoint.get("token_value")

            # Create and initialize Proxmox client
            endpoint = ProxmoxClient(
                host=host,
                user=user,
                token_name=token_name,
                token_value=token_value,
                verify_ssl=False
            )

            # Schedule the monitor method to be run every <frequency> minutes
            # We also pass the endpoint as a parameter to this method
            self.schedule(self.monitor, timedelta(minutes=frequency), (endpoint,))

    def fastcheck(self) -> Status:
        """
        Use to check if the extension can run.
        If this Activegate cannot run this extension, you can
        raise an Exception or return StatusValue.ERROR.
        This does not run for OneAgent extensions.
        """
        return Status(StatusValue.OK)

    def monitor(self, endpoint: dict):
        endpoint.initialize_proxmoxapi()

        # Fetch cluster status
        clusterStatusRequest = "cluster/status"
        cluster_status_get = endpoint.get_metrics(clusterStatusRequest)
        # self.logger.info(f"Collected cluster level status info")

        # Parse the JSON string
        cluster_status = json.loads(cluster_status_get)
        self.logger.info(f"Collected cluster level status info: {cluster_status}")

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
                    self.logger.error(f"Unexpected item type: {type(item)} - {item}")
        else:
            self.logger.error(f"cluster_status is not a list. Check the source of the data.")

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
        # self.logger.info(f"Collected cluster level dimensions: {cluster_dimensions}")

        # Sending to metrics server for cluster
        self.report_metric(
            "proxmox.cluster.node.count", cluster_node_count, cluster_dimensions
        )
        self.report_metric(
            "proxmox.cluster.node.online.count", cluster_node_online_count, cluster_dimensions
        )

        self.logger.info(f"Sent to metrics server for cluster: {cluster_name} with dimensions: {cluster_dimensions}")

        # Fetch cluster HA status
        clusterHaStatusRequest = "cluster/ha/status/current"
        cluster_ha_status_get = endpoint.get_metrics(clusterHaStatusRequest)
        # self.logger.info(f"Collected cluster high availability status info")

        # Parse the JSON string
        cluster_ha_status = json.loads(cluster_ha_status_get)
        self.logger.info(f"Collected cluster high availability status info: {cluster_ha_status}")      


        # Ensure cluster_ha_status is a list
        if isinstance(cluster_ha_status, list):
            cluster_ha_info = {}

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
                    self.logger.error(f"Unexpected item type: {type(item)} - {item}")
        else:
            self.logger.error(f"cluster_status is not a list. Check the source of the data.")

        cluster_ha_quorate = cluster_ha_info.get("quorate")
        cluster_ha_status_value = cluster_ha_info.get("status")

        if cluster_ha_status_value == "OK":
            cluster_ha_status_value = 1
        else:
            cluster_ha_status_value = 0
            
        # Sending to metrics server for cluster HA info
        self.report_metric(
            "proxmox.cluster.ha.quorate", cluster_ha_quorate, cluster_dimensions
        )

        self.report_metric(
            "proxmox.cluster.ha.status", cluster_ha_status_value, cluster_dimensions
        )

        self.executor.submit(self.collect_nodes, endpoint, node_info_list, cluster_dimensions)
        self.executor.submit(self.collect_storage, endpoint, node_info_list, cluster_dimensions)
        self.executor.submit(self.collect_qemuvm, endpoint, node_info_list, cluster_dimensions)
        self.executor.submit(self.collect_lxc, endpoint, node_info_list, cluster_dimensions)
        self.executor.submit(self.collect_service, endpoint, node_info_list, cluster_dimensions)

    def collect_nodes(self, endpoint, node_info_list, parent_dimensions: dict):
        # Fetch metrics for each node in cluster
        for node in node_info_list:
            node_name = node['name']
            nodeRequest = "nodes/" + node_name
            nodeMetricsRequest = nodeRequest + "/status"

            # Returns the metrics for each node
            node_metrics = endpoint.get_metrics(nodeMetricsRequest)

            # Parse the JSON string
            node_data = json.loads(node_metrics)

            # Extract Node info
            node_online = node['online']
            node_ip = node['ip']
            node_id = node['id']

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
            idle = idle * 100
            cpu = node_data["cpu"]
            cpu = cpu * 100
            uptime = node_data["uptime"]
            wait = node_data["wait"]
            wait = wait * 100

            # Extract memory metrics
            memory_used = node_data["memory"]["used"]
            memory_total = node_data["memory"]["total"]
            memory_free = node_data["memory"]["free"]

            # Extract load averages
            loadavg_1m = float(node_data["loadavg"][0])
            loadavg_5m = float(node_data["loadavg"][1])
            loadavg_15m = float(node_data["loadavg"][2])

            # Build node dimensions
            node_dimensions = {
                **parent_dimensions,
                "node": node_name,
                "nodeip": node_ip,
                "nodeid": node_id,
            }

            # Sending to metrics server for node
            self.report_metric(
                "proxmox.node.online", node_online, node_dimensions
            )
            self.report_metric(
                "proxmox.node.swap.free", swap_free, node_dimensions
            )
            self.report_metric(
                "proxmox.node.swap.total", swap_total, node_dimensions
            )
            self.report_metric(
                "proxmox.node.swap.used", swap_used, node_dimensions
            )
            self.report_metric(
                "proxmox.node.rootfs.avail", rootfs_avail, node_dimensions
            )
            self.report_metric(
                "proxmox.node.rootfs.used", rootfs_used, node_dimensions
            )
            self.report_metric(
                "proxmox.node.rootfs.free", rootfs_free, node_dimensions
            )
            self.report_metric(
                "proxmox.node.rootfs.total", rootfs_total, node_dimensions
            )
            self.report_metric(
                "proxmox.node.cpu.usage", cpu, node_dimensions
            )
            self.report_metric(
                "proxmox.node.cpu.wait", wait, node_dimensions
            )
            self.report_metric(
                "proxmox.node.cpu.idle", idle, node_dimensions
            )
            self.report_metric(
                "proxmox.node.uptime", uptime, node_dimensions
            )
            self.report_metric(
                "proxmox.node.memory.free", memory_free, node_dimensions
            )
            self.report_metric(
                "proxmox.node.memory.total", memory_total, node_dimensions
            )
            self.report_metric(
                "proxmox.node.memory.used", memory_used, node_dimensions
            )
            self.report_metric(
                "proxmox.node.loadavg.1min", loadavg_1m, node_dimensions
            )
            self.report_metric(
                "proxmox.node.loadavg.5min", loadavg_5m, node_dimensions
            )
            self.report_metric(
                "proxmox.node.loadavg.15min", loadavg_15m, node_dimensions
            )
            self.logger.info(f"Sent to metrics server for node: {node_name} wirh dimensions: {node_dimensions}")

    def collect_storage(self, endpoint, node_info_list, parent_dimensions: dict):
        # Fetch storage metrics for each node in cluster
        for node in node_info_list:
            node_name = node['name']
            nodeRequest = "nodes/" + node_name
            nodeStorageRequest = nodeRequest + "/storage"
            
            node_storage_metrics = endpoint.get_metrics_2(nodeStorageRequest)

            # Parse the JSON string
            storage_data = json.loads(node_storage_metrics)

            # Extract Node info
            node_id = node['id']

            # Loop through each storage entry for this node
            for entry in storage_data:
                if entry.get("active") == 1 and entry.get("enabled") == 1:       
                    storage_name = entry.get("storage")
                    storage_total = entry.get("total")
                    storage_used = entry.get("used")
                    storage_avail = entry.get("avail")
                    storage_type = entry.get("type")

                    # Build storage dimensions
                    storage_dimensions = {
                        **parent_dimensions,
                        "node": node_name,
                        "nodeid": node_id,
                        "nodestorage": storage_name,
                        "nodestoragetype": storage_type
                    }

                    # Sending to metrics server for storage
                    self.report_metric(
                        "proxmox.node.storage.total", storage_total, storage_dimensions
                    )
                    self.report_metric(
                        "proxmox.node.storage.used", storage_used, storage_dimensions
                    )
                    self.report_metric(
                        "proxmox.node.storage.avail", storage_avail, storage_dimensions
                    )
                    self.logger.info(f"Sent to metrics server for storage: {storage_name} for node: {node_name} with dimensions: {storage_dimensions}")

    def collect_qemuvm(self, endpoint, node_info_list, parent_dimensions: dict):
        # Fetch Qemu-VM metrics for each node in cluster
        for node in node_info_list:
            node_name = node['name']
            nodeRequest = "nodes/" + node_name
            nodeVmRequest = nodeRequest + "/qemu"
            
            # Fetching VM metrics
            node_vm_entries = endpoint.get_metrics_2(nodeVmRequest)

            # Parse the JSON string
            vm_entry_data = json.loads(node_vm_entries)

            # Extrace Node info
            node_id = node['id']

            # Loop through each VM entry for this node to get list of VMs
            for entry in vm_entry_data:
                if entry.get("status") == "running":
                    vm_name = entry.get("name")
                    vm_id = entry.get("vmid")

                    #all_ips = []
                    all_ips = ''

                    try:
                        vmIPSubRequest = nodeVmRequest + "/" + str(vm_id) + "/agent/network-get-interfaces"
                        vm_ip_info = endpoint.get_metrics_2(vmIPSubRequest) 
                        agent_info = json.loads(vm_ip_info)
                        
                        for interface in agent_info.get('result', []):
                            mac_addr = interface.get('hardware-address', 'Unknown')
                            for ip in interface.get('ip-addresses', []):
                                ip_addr = ip.get('ip-address')
                                if ip_addr and ip_addr != '127.0.0.1' and ':' not in ip_addr:  # exclude loopback and IPv6
                                    # self.logger.info(f"    IP: {ip_addr} | MAC: {mac_addr}")
                                    all_ips = ip_addr #if all_ips == '' else all_ips + ', ' + ip_addr
                                    # self.logger.info(f"Collected IP: {all_ips} for VM: {vm_name} (ID: {vm_id}) on node: {node_name}")
                    except Exception as e:
                        print(f"    Could not retrieve IP/MAC: {e}")

                    # Build VM dimensions with VM IP
                    vm_dimensions = {
                        **parent_dimensions,
                        "node": node_name,
                        "nodeid": node_id,
                        "vmname": vm_name,
                        "vmid": vm_id,
                        "vmips": all_ips
                    }

                    # Making request to retrieve metrics for each VM running on the node.
                    nodeVmSubRequest = nodeVmRequest + "/" + str(vm_id) + "/status/current"
                    node_vm_metrics = endpoint.get_metrics_2(nodeVmSubRequest)

                    vm_metrics = json.loads(node_vm_metrics)

                    vm_netout = vm_metrics.get("netout")
                    vm_uptime = vm_metrics.get("uptime")
                    vm_freemem = vm_metrics.get("freemem")
                    vm_maxdisk = vm_metrics.get("maxdisk")
                    vm_balloon = vm_metrics.get("balloon")
                    vm_diskwrite = vm_metrics.get("diskwrite")
                    vm_netin = vm_metrics.get("netin")
                    vm_qmpstatus = vm_metrics.get("qmpstatus")
                    vm_diskread = vm_metrics.get("diskread")
                    vm_mem = vm_metrics.get("mem")
                    vm_cpu = vm_metrics.get("cpu")
                    vm_cpu = vm_cpu * 100
                    vm_cpus = vm_metrics.get("cpus")
                    vm_maxmem = vm_metrics.get("maxmem")
                    vm_status = vm_metrics.get("status")

                    if vm_qmpstatus == "running":
                        vm_qmpstatus = 1
                    else:
                        vm_qmpstatus = 0

                    if vm_status == "running":
                        vm_status = 1
                    else:
                        vm_status = 0                        

                    # Sending metrics to metric server for VM
                    self.report_metric(
                        "proxmox.vm.memory.free", vm_freemem, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.balloon", vm_balloon, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.qmp.status", vm_qmpstatus, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.network.netin", vm_netin, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.network.netout", vm_netout, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.disk.write", vm_diskwrite, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.disk.max", vm_maxdisk, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.disk.read", vm_diskread, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.memory.max", vm_maxmem, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.memory.mem", vm_mem, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.cpu.usable", vm_cpus, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.cpu.usage", vm_cpu, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.uptime", vm_uptime, vm_dimensions
                    )
                    self.report_metric(
                        "proxmox.vm.status", vm_status, vm_dimensions
                    )
                    self.logger.info(f"Sent to metrics server for VM: {vm_name} for node: {node_name} with dimensions: {vm_dimensions}")

    def collect_lxc(self, endpoint, node_info_list, parent_dimensions: dict):
        # Fetch LXC-Container metrics for each node in cluster
        for node in node_info_list:
            node_name = node['name']
            nodeRequest = "nodes/" + node_name
            nodeLXCRequest = nodeRequest + "/lxc"
            
            # Fetching VM metrics
            node_lxc_entries = endpoint.get_metrics_2(nodeLXCRequest)

            # Parse the JSON string
            lxc_entry_data = json.loads(node_lxc_entries)

            # Extrace Node info
            node_id = node['id']

            # Loop through each VM entry for this node to get list of VMs
            for entry in lxc_entry_data:
                if entry.get("status") == "running":
                    lxc_name = entry.get("name")
                    lxc_id = entry.get("vmid")

                    # Making request to retrieve metrics for each VM running on the node.
                    nodeLXCSubRequest = nodeLXCRequest + "/" + str(lxc_id) + "/status/current"
                    node_lxc_metrics = endpoint.get_metrics_2(nodeLXCSubRequest)
                    
                    lxc_metrics = json.loads(node_lxc_metrics)

                    lxc_netout = lxc_metrics.get("netout")
                    lxc_uptime = lxc_metrics.get("uptime")
                    lxc_mawswap = lxc_metrics.get("maxswap")
                    lxc_diskwrite = lxc_metrics.get("diskwrite")
                    lxc_netin = lxc_metrics.get("netin")
                    lxc_diskread = lxc_metrics.get("diskread")
                    lxc_mem = lxc_metrics.get("mem")
                    lxc_cpu = lxc_metrics.get("cpu")
                    lxc_cpu = lxc_cpu * 100
                    lxc_cpus = lxc_metrics.get("cpus")
                    lxc_maxmem = lxc_metrics.get("maxmem")
                    lxc_status = lxc_metrics.get("status")
                    lxc_disk = lxc_metrics.get("disk")
                    lxc_swap = lxc_metrics.get("swap")
                    lxc_maxdisk = lxc_metrics.get("maxdisk")

                    if lxc_status == "running":
                        lxc_status = 1
                    else:
                        lxc_status = 0            

                    # Build VM dimensions
                    lxc_dimensions = {
                        **parent_dimensions,
                        "node": node_name,
                        "nodeid": node_id,
                        "lxcname": lxc_name,
                        "lxcid": lxc_id,
                        "lxctype": "lxc"
                    }
                    # Sending metrics to metric server for VM
                    self.report_metric(
                        "proxmox.lxc.network.netout", lxc_netout, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.uptime", lxc_uptime, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.swap.max", lxc_mawswap, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.disk.write", lxc_diskwrite, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.network.netin", lxc_netin, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.disk.read", lxc_diskread, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.memory.mem", lxc_mem, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.cpu.usage", lxc_cpu, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.cpu.usable", lxc_cpus, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.memory.max", lxc_maxmem, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.status", lxc_status, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.disk.usage", lxc_disk, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.swap.usage", lxc_swap, lxc_dimensions
                    )
                    self.report_metric(
                        "proxmox.lxc.disk.max", lxc_maxdisk, lxc_dimensions
                    )
                    self.logger.info(f"Sent to metrics server for VM: {lxc_name} for node: {node_name} with dimensions: {lxc_dimensions}")

    def collect_service(self, endpoint, node_info_list, parent_dimensions: dict):
        # Fetch services status for each node in cluster

        for node in node_info_list:
            node_name = node['name']
            nodeRequest = "nodes/" + node_name
            nodeserviceRequest = nodeRequest + "/services"
            node_service_metrics = endpoint.get_metrics_2(nodeserviceRequest)

            # Parse the JSON string
            service_data = json.loads(node_service_metrics)

            # Extrace Node info
            node_id = node['id']

            # Loop through each service entry for this node
            for entry in service_data:

                service_name = entry.get("name")
                service_id = entry.get("service")
                service_activestate = entry.get("active-state")
                service_active = entry.get("active")
                service_unitstate = entry.get("unit-state")

                if service_activestate == "active": service_activestate = 1 
                else: service_activestate = 0

                if service_active == "running": service_active = 1 
                else: service_active = 0                

                if service_unitstate == "enabled": service_unitstate = 1 
                else: service_unitstate = 0  

                # Build node service dimensions
                service_dimensions = {
                    **parent_dimensions,
                    "node": node_name,
                    "nodeid": node_id,
                    "service": service_id,
                    "service_name": service_name
                }

                # Sending metrics to metric server for node services
                self.report_metric(
                    "proxmox.node.service.state", service_active, service_dimensions
                )
                self.report_metric(
                    "proxmox.node.service.activestate", service_active, service_dimensions
                )
                self.report_metric(
                    "proxmox.node.service.unitstate", service_unitstate, service_dimensions
                )
                self.logger.info(f"Sent to metrics server for service: {service_name} for node: {node_name} with dimensions: {service_dimensions}")

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
    ProxmoxExtension().run()

if __name__ == "__main__":
    main()
