# custom:com.dynatrace.proxmox

**Latest version:** 0.0.11
This extension is built using the Dynatrace Extension 2.0 Framework.
This means it will benefit of additional assets that can help you browse through the data.

## Topology

This extension will create the following types of entities:
* Cluster (proxmox:cluster)
* Node (proxmox:node)
* Virtual Machine (proxmox:vm)

## Metrics

This extension will collect the following metrics:
* Split by Cluster:
  * Node Count (`proxmox.cluster.node.count`)
    Total Nodes running in the Cluster (as Count)
  * Node Online Count (`proxmox.cluster.node.online.count`)
    Total Nodes running and online in the Cluster (as Count)
* Split by Cluster, Node:
  * Online Status (`proxmox.node.online`)
    Running State of the node (as State)
  * CPU Used (`proxmox.node.cpu.usage`)
    The current cpu usage (as Percent)
  * CPU Wait (`proxmox.node.cpu.wait`)
    The current cpu wait (as Percent)
  * CPU Idle (`proxmox.node.cpu.idle`)
    The current cpu idle (as Count)
  * Memory Free (`proxmox.node.memory.free`)
    The free memory in bytes (as Byte)
  * Memory Total (`proxmox.node.memory.total`)
    The total memory in bytes (as Byte)
  * Memory Used (`proxmox.node.memory.used`)
    The used memory in bytes (as Byte)
  * Node Uptime (`proxmox.node.uptime`)
    Node uptime in seconds (as Second)
  * CPU Load (1m) (`proxmox.node.loadavg.1min`)
    Average 1 minute CPU Load (as Percent)
  * CPU Load (5m) (`proxmox.node.loadavg.5min`)
    Average 5 minute CPU Load (as Percent)
  * CPU Load (15m) (`proxmox.node.loadavg.15min`)
    Average 15 minute CPU Load (as Percent)
  * Root FS Available (`proxmox.node.rootfs.avail`)
    The available bytes in the root filesystem (as Byte)
  * Root FS Used (`proxmox.node.rootfs.used`)
    The used bytes in the root filesystem (as Byte)
  * Root FS Free (`proxmox.node.rootfs.free`)
    The free bytes in the root filesystem (as Byte)
  * Root FS Total (`proxmox.node.rootfs.total`)
    The total bytes in the root filesystem (as Byte)
  * Swap Free (`proxmox.node.swap.free`)
    The free swap space (as Byte)
  * Swap Total (`proxmox.node.swap.total`)
    The total swap space (as Byte)
  * Swap Used (`proxmox.node.swap.used`)
    The used swap space (as Byte)
  * Storage Total (`proxmox.node.storage.total`)
    Total storage space in bytes (as Byte)
  * Storage Used (`proxmox.node.storage.used`)
    Used storage space in bytes (as Byte)
  * Storage Available (`proxmox.node.storage.avail`)
    Available storage space in bytes (as Byte)
  * Service State (`proxmox.node.service.state`)
    Running State of the service (as State)
  * Service Active State (`proxmox.node.service.activestate`)
    Active State of the service (as State)
  * Service Unit State (`proxmox.node.service.unitstate`)
    Unit State of the service (as State)
* Split by Cluster, Node, Virtual Machine:
  * Memory Free (`proxmox.vm.freemem`)
    Currently free memory in bytes (as Byte)
  * Balloon Memory (`proxmox.vm.balloon`)
    Currently Balloon memory in bytes (as Byte)
  * QMP Monitor Status (`proxmox.vm.qmpstatus`)
    VM run state from the query-status QMP monitor command (as State)
  * Network Ingress (`proxmox.vm.network.netin`)
    The amount of traffic in bytes that was sent to the guest over the network since it was started (as Byte)
  * Network Egress (`proxmox.vm.network.netout`)
    The amount of traffic in bytes that was sent from the guest over the network since it was started (as Byte)
  * Disk Write (`proxmox.vm.disk.diskwrite`)
    The amount of bytes the guest wrote from it's block devices since the guest was started (as Byte)
  * Disk Size (`proxmox.vm.disk.maxdisk`)
    Root disk size in bytes (as Byte)
  * Disk Read (`proxmox.vm.disk.diskread`)
    The amount of bytes the guest read from it's block devices since the guest was started (as Byte)
  * Memory Total (`proxmox.vm.memory.max`)
    Maximum memory in bytes (as Byte)
  * Memory Used (`proxmox.vm.memory.mem`)
    Currently used memory in bytes (as Byte)
  * CPU Usable (`proxmox.vm.cpu.cpuusable`)
    Maximum usable CPUs (as Percent)
  * CPU Usage (`proxmox.vm.cpu.cpuusage`)
    Current CPU usage (as Percent)
  * VM Uptime (`proxmox.vm.uptime`)
    Uptime in seconds (as Second)
  * VM Status (`proxmox.vm.status`)
    Running Status of the VM (as State)

# Configuration

## Feature sets

Feature sets can be used to opt in and out of metric data collection.
This extension groups together metrics within the following feature sets:

* default

