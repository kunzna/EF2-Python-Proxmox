# Knowledge Transfer — Proxmox VE Monitoring Extension

**Audience:** new engineers joining the team or operators getting onboarded.
**Purpose:** broad-scope reference for the extension. Use it as a glossary and a configuration handbook. Sister documents handle the depths:

| For... | Read |
|---|---|
| The 30-second overview | [README.md](README.md) |
| The internal mechanics of the code | [ARCHITECTURE.md](ARCHITECTURE.md) |
| How to install/deploy the extension | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Glossaries, field references, catalogues | This document |

---

## Table of contents

1. [Purpose](#1-purpose)
2. [Repository layout](#2-repository-layout)
3. [Configuration field reference](#3-configuration-field-reference)
4. [Metrics catalogue](#4-metrics-catalogue)
5. [Topology catalogue](#5-topology-catalogue)
6. [Feature sets](#6-feature-sets)
7. [Alerts](#7-alerts)
8. [Glossary — Proxmox VE](#8-glossary--proxmox-ve)
9. [Glossary — Dynatrace EF2](#9-glossary--dynatrace-ef2)
10. [Where to look next](#10-where-to-look-next)

---

## 1. Purpose

The extension provides **full-stack monitoring** for Proxmox Virtual Environment clusters. It answers operational questions every `frequency` seconds:

| Question | How it's answered |
|---|---|
| Is the cluster healthy? | `GET cluster/status` → node count, online count, HA quorate/status, SDN status |
| Is HA functioning? | `GET cluster/ha/status/current` → quorate value, overall HA status |
| How loaded is each node? | `GET nodes/{node}/status` → CPU, memory, swap, rootfs, load average, uptime |
| How much storage is in use? | `GET nodes/{node}/storage` → capacity per active storage volume |
| What systemd services are running? | `GET nodes/{node}/services` → state, active-state, unit-state per service |
| How are the VMs performing? | `GET nodes/{node}/qemu/{vmid}/status/current` → CPU, memory, disk, network |
| How are the containers performing? | `GET nodes/{node}/lxc/{lxcid}/status/current` → CPU, memory, disk, network |

Each answer becomes a metric datapoint in Dynatrace with full dimension labels for the cluster, node, and (where applicable) VM or container. SLOs, dashboards, and alerts can be built on top of these metrics.

The extension is **not** an agent deployed inside VMs. It talks to the Proxmox REST API from outside — it sees the same data the Proxmox web UI shows. Per-process metrics inside VMs require a separate solution (OneAgent or another tool).

---

## 2. Repository layout

```
EF2-Python-Proxmox/
│
├── proxmox/                          ← Python package (the extension's runtime)
│   ├── __init__.py                   ← empty marker file
│   ├── __main__.py                   ← all production runtime logic (~680 lines)
│   ├── proxmox_api.py                ← ProxmoxClient wrapper around proxmoxer
│   ├── common_functions.py           ← JSON validation utility
│   ├── proxmox_testing_api.py        ← extended client for dev/testing only
│   └── proxmoxtesting.py             ← standalone test script, not production
│
├── extension/                        ← EF2 manifest folder
│   ├── extension.yaml                ← metrics, topology, feature sets, version, requirements
│   ├── activationSchema.json         ← UI configuration schema
│   └── documents/
│       └── proxmox_overview.dashboard.json  ← built-in overview dashboard
│
├── setup.py                          ← Python packaging; version read from extension.yaml
├── ruff.toml                         ← linter config
│
├── activation.json                   ← LOCAL DEV ONLY — config used by `dt-sdk run`
├── secrets.json                      ← LOCAL DEV ONLY — placeholder, never real secrets
│
├── README.md                         ← entry point, links to all other docs
├── ARCHITECTURE.md                   ← internal mechanics deep-dive
├── DEPLOYMENT.md                     ← install/rollout guide
├── KNOWLEDGE_TRANSFER.md             ← this document
└── LICENSE
```

The production runtime is **three files**: `__main__.py`, `proxmox_api.py`, and `common_functions.py`. Everything else is configuration, packaging, tooling, or documentation.

---

## 3. Configuration field reference

Every field below is configured per endpoint in the monitoring configuration UI. The schema source of truth is [extension/activationSchema.json](extension/activationSchema.json).

| Field | Type | Default | Purpose |
|---|---|---|---|
| `cluster_name` | text | `""` | Friendly display label for this endpoint. Appears in the UI monitoring configuration summary. **Not used in any metric dimension** — the cluster name in metrics comes from the Proxmox API. |
| `host` | list of text | `["127.0.0.1"]` | IP address of the Proxmox master cluster node. The schema accepts a list, but only the first entry is used by the runtime. |
| `user` | text | `root@pam` | Proxmox username in `user@realm` format. Must match the realm where the API token was created. |
| `token_name` | text | `api` | The name (ID) of the API token as shown in the Proxmox UI under the user's API Tokens. |
| `token_value` | secret | `""` | The secret value of the API token. Stored encrypted in the Dynatrace tenant. |
| `frequency` | integer (seconds) | `60` | How often a full collection cycle runs for this endpoint. Minimum practical value depends on cluster size and API response time. |

### How credentials are used at runtime

The extension combines `user`, `token_name`, and `token_value` into the `proxmoxer.ProxmoxAPI` constructor as:

```python
ProxmoxAPI(host, user=user, token_name=token_name, token_value=token_value, verify_ssl=False)
```

`proxmoxer` sends these as an HTTP `Authorization` header in the format:

```
PVEAPIToken=user@realm!token_name:token_value
```

No session management or cookie handling is involved.

---

## 4. Metrics catalogue

### Cluster metrics

Emitted once per cluster per cycle. Source: `GET cluster/status` and `GET cluster/ha/status/current`.

| Key | Unit | Description | Dimensions |
|---|---|---|---|
| `proxmox.cluster.node` | Count | Total nodes registered in the cluster | cluster, clusterid |
| `proxmox.cluster.node.online` | Count | Nodes currently online | cluster, clusterid |
| `proxmox.cluster.ha.quorate` | Count | Quorum state value from the HA manager | cluster, clusterid |
| `proxmox.cluster.ha.status` | State | 1 if HA status is "OK", 0 otherwise | cluster, clusterid |
| `proxmox.cluster.sdn.status` | State | 1 if all SDN entries report "ok", 0 if any are degraded | cluster, clusterid |

### Node metrics

Emitted once per node per cycle. Source: `GET nodes/{node}/status`.

| Key | Unit | Description | Dimensions |
|---|---|---|---|
| `proxmox.node.online` | State | 1 if the node is online in the cluster | cluster, clusterid, node, nodeid |
| `proxmox.node.cpu.usage` | Percent | CPU utilization (fraction × 100) | cluster, clusterid, node, nodeid |
| `proxmox.node.cpu.wait` | Percent | CPU I/O wait (fraction × 100) | cluster, clusterid, node, nodeid |
| `proxmox.node.cpu.idle` | Percent | CPU idle time (fraction × 100) | cluster, clusterid, node, nodeid |
| `proxmox.node.memory.used` | Byte | Memory currently in use | cluster, clusterid, node, nodeid |
| `proxmox.node.memory.free` | Byte | Free memory | cluster, clusterid, node, nodeid |
| `proxmox.node.memory.total` | Byte | Total physical memory | cluster, clusterid, node, nodeid |
| `proxmox.node.swap.used` | Byte | Swap in use | cluster, clusterid, node, nodeid |
| `proxmox.node.swap.free` | Byte | Free swap | cluster, clusterid, node, nodeid |
| `proxmox.node.swap.total` | Byte | Total swap space | cluster, clusterid, node, nodeid |
| `proxmox.node.rootfs.used` | Byte | Root filesystem used | cluster, clusterid, node, nodeid |
| `proxmox.node.rootfs.free` | Byte | Root filesystem free | cluster, clusterid, node, nodeid |
| `proxmox.node.rootfs.total` | Byte | Root filesystem total | cluster, clusterid, node, nodeid |
| `proxmox.node.rootfs.avail` | Byte | Root filesystem available | cluster, clusterid, node, nodeid |
| `proxmox.node.loadavg.1min` | Count | 1-minute load average | cluster, clusterid, node, nodeid |
| `proxmox.node.loadavg.5min` | Count | 5-minute load average | cluster, clusterid, node, nodeid |
| `proxmox.node.loadavg.15min` | Count | 15-minute load average | cluster, clusterid, node, nodeid |
| `proxmox.node.uptime` | Second | Node uptime | cluster, clusterid, node, nodeid |
| `proxmox.node.vm` | Count | Running QEMU VMs on this node | cluster, clusterid, node, nodeid |
| `proxmox.node.lxc` | Count | Running LXC containers on this node | cluster, clusterid, node, nodeid |

### Node-Storage metrics

Emitted once per active+enabled storage volume per node per cycle. Source: `GET nodes/{node}/storage`.

| Key | Unit | Description | Dimensions |
|---|---|---|---|
| `proxmox.node.storage.total` | Byte | Total storage capacity | cluster, clusterid, node, nodeid, nodestorage, nodestoragetype |
| `proxmox.node.storage.used` | Byte | Used storage | cluster, clusterid, node, nodeid, nodestorage, nodestoragetype |
| `proxmox.node.storage.avail` | Byte | Available storage | cluster, clusterid, node, nodeid, nodestorage, nodestoragetype |

### Node-Services metrics

Emitted once per systemd service per node per cycle. Source: `GET nodes/{node}/services`. Only services tracked by Proxmox are included (not all systemd services on the host).

| Key | Unit | Description | Dimensions |
|---|---|---|---|
| `proxmox.node.service.state` | State | 1 if the service is running | cluster, clusterid, node, nodeid, service, service_name |
| `proxmox.node.service.activestate` | State | 1 if the service active-state is "active" | cluster, clusterid, node, nodeid, service, service_name |
| `proxmox.node.service.unitstate` | State | 1 if the unit-state is "enabled" | cluster, clusterid, node, nodeid, service, service_name |

### VM (QEMU) metrics

Emitted once per **running** QEMU VM per node per cycle. Source: `GET nodes/{node}/qemu/{vmid}/status/current`. Stopped VMs are not collected.

| Key | Unit | Description | Dimensions |
|---|---|---|---|
| `proxmox.vm.cpu.usage` | Count | CPU usage fraction | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.cpu.usable` | Percent | Allocated CPU count × 100 | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.memory.mem` | Byte | Current memory usage | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.memory.max` | Byte | Maximum allocated memory | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.memory.free` | Byte | Free memory (if reported by guest agent) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.balloon` | Byte | Current balloon target | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.disk.used` | Byte | Disk space used | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.disk.max` | Byte | Maximum disk size | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.disk.read` | Byte | Disk read bytes (cumulative) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.disk.write` | Byte | Disk write bytes (cumulative) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.network.netin` | Byte | Network ingress bytes (cumulative) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.network.netout` | Byte | Network egress bytes (cumulative) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.status` | State | 1 if VM status is "running" | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.qmp.status` | State | 1 if QMP status is "running" | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.uptime` | Second | VM uptime | cluster, clusterid, node, nodeid, vmname, vmid, vmips |

### Dimension: `vmips`

The `vmips` dimension contains a comma-separated list of IPv4 addresses collected from the QEMU guest agent. It is empty if the guest agent is not running in the VM. IPv6 addresses and loopback (`127.0.0.1`) are excluded.

### Container (LXC) metrics

Emitted once per **running** LXC container per node per cycle. Source: `GET nodes/{node}/lxc/{lxcid}/status/current`. Stopped containers are not collected.

| Key | Unit | Description | Dimensions |
|---|---|---|---|
| `proxmox.lxc.cpu.usage` | Count | CPU usage fraction | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.cpu.usable` | Count | Allocated CPU count | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.memory.mem` | Byte | Current memory usage | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.memory.max` | Byte | Maximum allocated memory | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.swap.usage` | Byte | Current swap usage | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.swap.max` | Byte | Maximum swap | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.disk.usage` | Byte | Disk space used | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.disk.max` | Byte | Maximum disk size | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.disk.read` | Byte | Disk read bytes (cumulative) | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.disk.write` | Byte | Disk write bytes (cumulative) | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.network.netin` | Byte | Network ingress bytes (cumulative) | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.network.netout` | Byte | Network egress bytes (cumulative) | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.status` | State | 1 if container status is "running" | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.uptime` | Second | Container uptime | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |

### Dimension: `lxctype`

Always set to the literal string `"lxc"`. Reserved for future use if other container runtimes are added.

---

## 5. Topology catalogue

Four custom entity types are synthesized from metric dimensions, forming a strict hierarchy. Defined in [extension/extension.yaml](extension/extension.yaml) under `topology:`.

```
proxmox:cluster
    └── proxmox:node
            ├── proxmox:vm
            └── proxmox:container
```

| Entity type | Display name | ID pattern | Synthesized from |
|---|---|---|---|
| `proxmox:cluster` | Cluster | `proxmox_cluster_{cluster}` | Any `proxmox.*` metric |
| `proxmox:node` | Node | `proxmox_node_{cluster}_{node}` | `proxmox.node.*`, `proxmox.vm.*`, `proxmox.lxc.*` |
| `proxmox:vm` | Virtual Machine | `proxmox_vm_{cluster}_{node}_{vmid}` | `proxmox.vm.*` |
| `proxmox:container` | Container | `proxmox_container_{cluster}_{node}_{lxcid}` | `proxmox.lxc.*` |

Relationships are `RUNS_ON`:
- `proxmox:node` runs on `proxmox:cluster`
- `proxmox:vm` runs on `proxmox:node`
- `proxmox:container` runs on `proxmox:node`

Entities are created automatically when metric datapoints with matching dimensions arrive. The extension never calls a Dynatrace topology API. If a VM or container stops (and therefore stops emitting metrics), its entity will age out of the topology based on the tenant's entity retention policy.

---

## 6. Feature sets

Feature sets allow operators to selectively enable metric collection groups. Defined in [extension/extension.yaml](extension/extension.yaml) under `featureSets:`.

| Feature set | What it enables |
|---|---|
| `Cluster` | All `proxmox.cluster.*` metrics |
| `Node` | All `proxmox.node.*` core metrics (CPU, memory, swap, rootfs, load avg, uptime, vm/lxc counts) |
| `Node-Storage` | All `proxmox.node.storage.*` metrics |
| `Node-Services` | All `proxmox.node.service.*` metrics |
| `VM` | All `proxmox.vm.*` metrics |
| `CONTAINER` | All `proxmox.lxc.*` metrics |

All feature sets are enabled by default. Disable `Node-Services` or `Node-Storage` if the corresponding API calls are generating too much data or noise in environments with many services or storage volumes.

---

## 7. Alerts

**No alerts are currently shipped with the extension.** The `extension.yaml` does not include an `alerts:` section.

To add alerts:

1. Create one JSON file per alert under a new `extension/alerts/` directory.
2. Add an `alerts:` block in `extension.yaml`:

   ```yaml
   alerts:
     - path: alerts/proxmox_node_offline.json
     - path: alerts/proxmox_ha_status_failed.json
     - path: alerts/proxmox_vm_offline.json
   ```

3. Bump version, rebuild, sign, re-upload.

> Extensions ship alerts **disabled by default**. After upload, operators must enable each alert in the tenant UI. This prevents a release from spraying new alerts onto an unsuspecting on-call rotation.

Until shipped, build tenant-side **custom metric events** on these metric keys:

| Suggested alert | Metric | Threshold |
|---|---|---|
| Node offline | `proxmox.node.online` | value = 0 |
| HA status degraded | `proxmox.cluster.ha.status` | value = 0 |
| VM down unexpectedly | `proxmox.vm.status` | value = 0 |
| Node CPU saturated | `proxmox.node.cpu.usage` | value > 90 for N minutes |
| Node memory exhausted | `proxmox.node.memory.free` | value < threshold |

---

## 8. Glossary — Proxmox VE

| Term | Meaning |
|---|---|
| **Proxmox VE** | Proxmox Virtual Environment — an open-source server virtualization platform built on Debian Linux, supporting QEMU/KVM VMs and LXC containers. |
| **Cluster** | A group of Proxmox nodes managed together. Shares a common configuration store (Corosync). A "standalone" single-node install is also visible as a cluster with one node. |
| **Node** | A single physical or virtual server running the Proxmox VE hypervisor. |
| **QEMU VM** | A full virtual machine running under the QEMU/KVM hypervisor. Has its own kernel. Referenced by `vmid`. |
| **LXC Container** | A Linux container (OS-level virtualization). Shares the host kernel. Referenced by `vmid` in the Proxmox API but collected under `proxmox.lxc.*` metrics. |
| **HA (High Availability)** | Proxmox's built-in HA manager that can automatically restart VMs and containers on failure. Requires at least 3 nodes and a shared storage backend. |
| **HA Quorate** | Whether the cluster has quorum (majority of nodes agree). A cluster that loses quorum fences itself to prevent split-brain. |
| **SDN (Software-Defined Networking)** | Proxmox's optional network virtualization layer. Manages VNets, VLANs, and overlays. The `sdn.status` metric reflects the aggregate health of SDN zones. |
| **API Token** | A non-interactive credential associated with a Proxmox user. Consists of a token name (ID) and a token secret value. Used in place of username+password for API access. |
| **PVEAuditor** | A built-in Proxmox role that grants read-only access to all cluster resources. The recommended role for monitoring accounts. |
| **`proxmoxer`** | A Python library that wraps the Proxmox REST API. Used by this extension as the HTTP client. |
| **Guest Agent (QEMU)** | A small daemon (`qemu-guest-agent`) that runs inside a QEMU VM and exposes in-guest data (network interfaces, file system info) to the hypervisor via the QEMU monitor protocol (QMP). Required for `vmips` dimension population. |
| **QMP** | QEMU Machine Protocol — a JSON-based protocol for communicating with a running QEMU process. The `proxmox.vm.qmp.status` metric reflects whether the VM's QMP channel reports it as "running". |
| **Balloon** | A memory management technique where the hypervisor can reclaim memory from a VM using a "balloon driver" inside the VM. The `proxmox.vm.balloon` metric reflects the current balloon target in bytes. |
| **Storage** | A storage backend configured in Proxmox (e.g., local disk, NFS, Ceph, LVM). Each storage has a name and type. The extension only collects metrics for `active` and `enabled` storages. |

---

## 9. Glossary — Dynatrace EF2

| Term | Meaning |
|---|---|
| **EF2** | Extensions Framework 2.0. Dynatrace's current extension framework. The Python flavor lets you write extensions in standard Python. |
| **EEC** | Extension Execution Controller. A process running on an ActiveGate that hosts and supervises extension processes. This extension runs inside the EEC. |
| **ActiveGate** | A Dynatrace component that runs on a customer-managed host. EECs run on ActiveGates. Used here to provide network access to Proxmox from a Dynatrace-managed runtime. |
| **Activation context** | The execution context: `REMOTE` (runs on an ActiveGate/EEC — this extension's primary mode) or `LOCAL` (runs on a host alongside OneAgent). Both are supported. |
| **Monitoring configuration** | The activation document operators fill in via the UI. Validated against `activationSchema.json`. Stored in the tenant. One configuration can have multiple endpoints. |
| **`dt-sdk`** | The EF2 build/sign/upload CLI. Installed via `pip install "dt-extensions-sdk[cli]"`. |
| **Topology** | The set of custom entity types and relationships that get auto-synthesized from metric dimensions. Configured under `topology:` in `extension.yaml`. |
| **Source entity type** | The entity a given metric "belongs to". Determines which entity the metric appears under in the Dynatrace UI (`sourceEntityType` in `extension.yaml`). |
| **Feature set** | A named group of metric keys that can be enabled or disabled together in the monitoring configuration. Configured under `featureSets:` in `extension.yaml`. |
| **Custom metric event** | A tenant-side alert configuration that fires when a metric crosses a threshold. Can be shipped with the extension (under `alerts:`) or created tenant-side. |
| **Signing CA / Dev cert** | EF2 requires extensions to be signed. The tenant trusts a CA; engineers sign with developer certs chained to that CA. |
| **`dt-sdk run`** | A local development command that simulates one extension cycle using `activation.json` as the config source. Does not require a real EEC or tenant. |

---

## 10. Where to look next

| If you want to... | Go to |
|---|---|
| Install or deploy the extension | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Modify a collection method or add a new metric | [ARCHITECTURE.md §13](ARCHITECTURE.md#13-extension-points) |
| Understand the API client and request flow | [ARCHITECTURE.md §6](ARCHITECTURE.md#6-api-client-design) |
| Trace the per-cycle execution flow | [ARCHITECTURE.md §5](ARCHITECTURE.md#5-per-cycle-execution-flow) |
| Diagnose a deployment-time failure | [DEPLOYMENT.md §10](DEPLOYMENT.md#10-common-deployment-failures) |
| Understand a specific quirk or design tension | [ARCHITECTURE.md §12](ARCHITECTURE.md#12-design-quirks-and-known-tensions) |
| Read the runtime source | [proxmox/__main__.py](proxmox/__main__.py) |
| See the API client source | [proxmox/proxmox_api.py](proxmox/proxmox_api.py) |
| See the configurable fields directly | [extension/activationSchema.json](extension/activationSchema.json) |
| See the full metrics and topology manifest | [extension/extension.yaml](extension/extension.yaml) |
