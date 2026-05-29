# Architecture Deep-Dive — Proxmox VE Monitoring Extension

**Audience:** engineers maintaining or extending this extension.
**Scope:** internal mechanics, control flow, design decisions, and architectural quirks.
**Out of scope:** setup, deployment steps, customer-facing usage — see [KNOWLEDGE_TRANSFER.md](KNOWLEDGE_TRANSFER.md) for those.

---

## Table of contents

1. [System context](#1-system-context)
2. [Runtime model (EF2)](#2-runtime-model-ef2)
3. [Component map](#3-component-map)
4. [Configuration ingestion](#4-configuration-ingestion)
5. [Per-cycle execution flow](#5-per-cycle-execution-flow)
6. [API client design](#6-api-client-design)
7. [Metric collection methods](#7-metric-collection-methods)
8. [Metric model](#8-metric-model)
9. [Topology model](#9-topology-model)
10. [Concurrency model](#10-concurrency-model)
11. [Error handling](#11-error-handling)
12. [Design quirks and known tensions](#12-design-quirks-and-known-tensions)
13. [Extension points](#13-extension-points)
14. [Reference: file inventory](#14-reference-file-inventory)

---

## 1. System context

```
+-----------------------------+        +---------------------------+
|  Dynatrace tenant           |        |  Proxmox VE Cluster       |
|  - Metrics ingest           |        |  - Cluster API            |
|  - Topology model           |        |  - Nodes                  |
|  - Custom entities          |        |  - VMs (QEMU)             |
+--------------^--------------+        |  - LXC Containers         |
               |                       |  - Storage                |
               | report_metric         |  - Services               |
               |                       +-------------^-------------+
+--------------+---------------------+               |
|  EEC host (or OneAgent host)       |               |  HTTPS REST API
|  +------------------------------+  |               |  (proxmoxer library)
|  | proxmox extension            +--+---------------+
|  | (this extension, EF2 Python) |  |
|  +------------------------------+  |
+------------------------------------+
```

The extension runs on a Dynatrace EEC host (or OneAgent host) and connects to the Proxmox VE REST API over HTTPS. It uses the `proxmoxer` Python library as an HTTP client — there is no subprocess execution and no dependency on local Proxmox tooling.

This is the most important architectural fact: **the extension is a REST API client, not a CLI orchestrator**. It can run on any host with network reachability to the Proxmox cluster master node, regardless of what software is installed on that host.

---

## 2. Runtime model (EF2)

The extension extends `dynatrace_extension.Extension` ([proxmox/__main__.py:17](proxmox/__main__.py#L17)). EF2 drives the lifecycle:

| Phase | Method | What happens |
|---|---|---|
| Construct | [`__init__`](proxmox/__main__.py#L18) | Sets the `extension_name` string and creates a `ThreadPoolExecutor` with `max_workers=10`. |
| Pre-flight | [`fastcheck`](proxmox/__main__.py#L48) | Currently a no-op that always returns `StatusValue.OK`. No actual validation logic is run. |
| Schedule | [`initialize`](proxmox/__main__.py#L23) | Iterates `endpoints` from `activation_config`, creates one `ProxmoxClient` per endpoint, and calls `self.schedule(self.monitor, timedelta(seconds=frequency), (endpoint,))` once per endpoint. |
| Recurring | `monitor` | The scheduled callback that runs every `frequency` seconds per endpoint. |

`self.schedule()` is provided by the EF2 SDK; we do not own the timer loop. The SDK invokes the callback on a worker thread with the bound args.

`main()` ([proxmox/__main__.py](proxmox/__main__.py)) is the entrypoint — `setup.py` registers `proxmox` as the module and EF2 invokes it via `__main__`.

---

## 3. Component map

The runtime logic is split across three files:

```
proxmox/
├── __main__.py              ← ProxmoxExtension class (all collection logic)
│   ├── lifecycle
│   │   ├── __init__                          sets executor, extension_name
│   │   ├── fastcheck                         always returns OK
│   │   └── initialize                        creates ProxmoxClient per endpoint, schedules monitor
│   │
│   ├── scheduled entry point
│   │   └── monitor(endpoint)                 cluster + HA metrics, then fans out to 5 workers
│   │
│   └── collection workers (run in ThreadPoolExecutor)
│       ├── collect_nodes(endpoint, nodes, dims)      node-level metrics
│       ├── collect_storage(endpoint, nodes, dims)    storage metrics per node
│       ├── collect_qemuvm(endpoint, nodes, dims)     VM metrics per node
│       ├── collect_lxc(endpoint, nodes, dims)        LXC container metrics per node
│       └── collect_service(endpoint, nodes, dims)    service state per node
│
├── proxmox_api.py           ← ProxmoxClient class
│   ├── __init__             validates/coerces host, stores credentials
│   ├── initialize_proxmoxapi  creates proxmoxer.ProxmoxAPI connection
│   ├── get_metrics(request)   calls API, validates JSON, returns JSON string
│   └── get_metrics_2(request) delegates to get_metrics (kept for call-site clarity)
│
└── common_functions.py      ← common_functions.is_valid_json(data)
                                round-trip JSON validation utility
```

`proxmox_testing_api.py` and `proxmoxtesting.py` are **development-only** files. They are not imported by the production runtime and are not bundled in the release artifact by `dt-sdk build`.

---

## 4. Configuration ingestion

Configuration flows from `activationSchema.json` → Dynatrace UI → `activation_config` dict at runtime.

The schema ([extension/activationSchema.json](extension/activationSchema.json)) defines a `pythonRemote` / `pythonLocal` wrapper containing an `endpoints` list. Each endpoint exposes:

| Field | Type | Default | Purpose |
|---|---|---|---|
| `cluster_name` | text | `""` | Friendly label — appears in the UI summary but is **not** used as a metric dimension. |
| `host` | list of text | `["127.0.0.1"]` | IP address of the cluster master node. The schema allows a list for future expansion, but the code always uses only the first element. |
| `user` | text | `root@pam` | Proxmox username in `user@realm` format. |
| `token_name` | text | `api` | Name of the API token created in Proxmox. |
| `token_value` | secret | `""` | Secret value of the API token. Stored encrypted in the tenant. |
| `frequency` | integer (seconds) | `60` | Poll cadence. One full collection cycle per endpoint runs every `frequency` seconds. |

In code ([proxmox/__main__.py:25-46](proxmox/__main__.py#L25-L46)), `initialize` reads each endpoint with `endpoint.get(...)` and passes the values directly to `ProxmoxClient`. The `cluster_name` field is read from config but never forwarded to `ProxmoxClient` or used in any metric dimension — it exists purely as a UI label.

`activation.json` in the repo root is a *local development shim* — it is what `dt-sdk run` uses to simulate `activation_config` in a developer's shell. It is **not** what production uses; production config comes from the Dynatrace tenant.

---

## 5. Per-cycle execution flow

`monitor` ([proxmox/__main__.py:57](proxmox/__main__.py#L57)) runs the following sequence once per scheduled invocation per endpoint:

```
initialize_proxmoxapi()           ← re-establishes the proxmoxer connection each cycle
│
├── GET cluster/status
│   ├── parse cluster_info (id, name, node_count)
│   ├── parse node_info_list   [{id, name, online, local, ip}, ...]
│   └── parse sdn_info_list    [{id, node, status, sdn}, ...]
│   │
│   └─→ METRIC proxmox.cluster.node
│   └─→ METRIC proxmox.cluster.node.online
│   └─→ METRIC proxmox.cluster.sdn.status
│
├── GET cluster/ha/status/current
│   └── parse cluster_ha_info (quorate, status)
│   │
│   └─→ METRIC proxmox.cluster.ha.quorate
│   └─→ METRIC proxmox.cluster.ha.status
│
├── executor.submit(collect_nodes, ...)
├── executor.submit(collect_storage, ...)
├── executor.submit(collect_qemuvm, ...)
├── executor.submit(collect_lxc, ...)
└── executor.submit(collect_service, ...)
    (all five run concurrently in the thread pool)
```

The cluster-level metrics are always collected synchronously on the monitor's own thread before the worker threads are submitted. Node-level discovery (the `node_info_list`) is produced in this synchronous phase and then passed to all five workers.

Each worker iterates over `node_info_list` independently — they each make their own API calls per node without coordinating with each other.

---

## 6. API client design

`ProxmoxClient` ([proxmox/proxmox_api.py](proxmox/proxmox_api.py)) wraps `proxmoxer.ProxmoxAPI`:

```python
ProxmoxAPI(
    host,
    user=user,
    token_name=token_name,
    token_value=token_value,
    verify_ssl=False          # hardcoded — see §12
)
```

Authentication is **token-based** (`user@realm!token_name:token_value`). This is the Proxmox API token format — no session cookies, no interactive login. Each `ProxmoxAPI` call is a stateless HTTPS request.

`initialize_proxmoxapi()` is called at the **start of every monitor cycle**, not once at startup. This means a new `proxmoxer` session object is created each poll, which avoids stale connection state at the cost of a small per-cycle overhead.

### Request pattern

`get_metrics(request)` takes a path string such as `"nodes/pve1/status"` and calls:

```python
JSON = json.dumps(self.api(request).get())
```

`proxmoxer` resolves the path against the API root (`https://<host>:8006/api2/json/`) and returns a Python object. `json.dumps` serializes it back to a string for downstream `json.loads` in the collection methods. This round-trip (Python dict → JSON string → Python dict) is slightly inefficient but maintains a consistent interface across the code.

`get_metrics_2(request)` is an alias for `get_metrics` kept for call-site clarity — some callers use it to signal "this is a sub-resource call rather than a top-level status call."

### Host coercion

If `host` is passed as a Python list (as the activation schema allows), `__init__` silently coerces it to the first element and logs a warning. This prevents a `proxmoxer` TypeError at connect time.

---

## 7. Metric collection methods

### collect_nodes

For each node in `node_info_list`:

1. `GET nodes/{node}/status` — CPU, memory, swap, rootfs, load average, uptime
2. Emits all node-level metrics with `node_dimensions` = `{cluster, clusterid, node, nodeip, nodeid}`

CPU values are stored as fractions (0–1) by Proxmox and are multiplied by 100 before emission. Load averages are parsed from a 3-element list (`[1min, 5min, 15min]`).

### collect_storage

For each node:

1. `GET nodes/{node}/storage` — returns all storage volumes
2. Filters to `active == 1 AND enabled == 1` only — inactive or disabled storages are silently skipped
3. Emits storage metrics with `storage_dimensions` = `{cluster, clusterid, node, nodeid, nodestorage, nodestoragetype}`

### collect_qemuvm

For each node:

1. `GET nodes/{node}/qemu` — list of all VMs
2. Filters to `status == "running"` only — stopped VMs are not collected
3. For each running VM:
   - Attempts `GET nodes/{node}/qemu/{vmid}/agent/network-get-interfaces` to collect IP addresses. Failure is caught, logged as a warning, and does not abort collection.
   - `GET nodes/{node}/qemu/{vmid}/status/current` — full VM metrics
4. Emits VM metrics with `vm_dimensions` = `{cluster, clusterid, node, nodeid, vmname, vmid, vmips}`
5. After iterating all VMs, emits `proxmox.node.vm` (count of running VMs on this node)

`vm_cpus` (usable CPU count) is multiplied by 100 before emission to match the percent-scale convention used for CPU metrics.

### collect_lxc

Same pattern as `collect_qemuvm` but for LXC containers:

1. `GET nodes/{node}/lxc` — list of all containers
2. Filters to `status == "running"` only
3. `GET nodes/{node}/lxc/{lxcid}/status/current` per container
4. Emits with `lxc_dimensions` = `{cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype}`
5. After iterating, emits `proxmox.node.lxc` (count of running containers on this node)

### collect_service

For each node:

1. `GET nodes/{node}/services` — list of all systemd services tracked by Proxmox
2. Converts `active-state`, `active`, and `unit-state` string values to 0/1 integers
3. Emits with `service_dimensions` = `{cluster, clusterid, node, nodeid, service, service_name}`

---

## 8. Metric model

95+ metric keys are defined. The table below covers the key groupings; for the full list see [extension/extension.yaml](extension/extension.yaml).

### Cluster metrics

| Key | Description | Dimensions |
|---|---|---|
| `proxmox.cluster.node` | Total node count | cluster, clusterid |
| `proxmox.cluster.node.online` | Online node count | cluster, clusterid |
| `proxmox.cluster.ha.quorate` | HA quorate value | cluster, clusterid |
| `proxmox.cluster.ha.status` | HA status (1=OK, 0=not OK) | cluster, clusterid |
| `proxmox.cluster.sdn.status` | SDN status (1=ok, 0=degraded) | cluster, clusterid |

### Node metrics

| Key | Description | Dimensions |
|---|---|---|
| `proxmox.node.online` | Node online state | cluster, clusterid, node, nodeid |
| `proxmox.node.cpu.usage` | CPU usage % | cluster, clusterid, node, nodeid |
| `proxmox.node.cpu.wait` | CPU I/O wait % | cluster, clusterid, node, nodeid |
| `proxmox.node.cpu.idle` | CPU idle % | cluster, clusterid, node, nodeid |
| `proxmox.node.memory.{used,free,total}` | Memory bytes | cluster, clusterid, node, nodeid |
| `proxmox.node.swap.{used,free,total}` | Swap bytes | cluster, clusterid, node, nodeid |
| `proxmox.node.rootfs.{used,free,total,avail}` | Root filesystem bytes | cluster, clusterid, node, nodeid |
| `proxmox.node.loadavg.{1min,5min,15min}` | Load averages | cluster, clusterid, node, nodeid |
| `proxmox.node.uptime` | Node uptime (seconds) | cluster, clusterid, node, nodeid |
| `proxmox.node.vm` | Running VM count | cluster, clusterid, node, nodeid |
| `proxmox.node.lxc` | Running container count | cluster, clusterid, node, nodeid |

### Node-Storage metrics

| Key | Description | Dimensions |
|---|---|---|
| `proxmox.node.storage.{total,used,avail}` | Storage bytes | cluster, clusterid, node, nodeid, nodestorage, nodestoragetype |

### Node-Services metrics

| Key | Description | Dimensions |
|---|---|---|
| `proxmox.node.service.state` | Service running state (1=running) | cluster, clusterid, node, nodeid, service, service_name |
| `proxmox.node.service.activestate` | Active-state (1=active) | cluster, clusterid, node, nodeid, service, service_name |
| `proxmox.node.service.unitstate` | Unit-state (1=enabled) | cluster, clusterid, node, nodeid, service, service_name |

### VM metrics

| Key | Description | Dimensions |
|---|---|---|
| `proxmox.vm.cpu.usage` | VM CPU usage fraction | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.cpu.usable` | VM usable CPU % (cpus × 100) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.memory.{mem,max,free}` | Memory bytes | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.balloon` | Balloon memory bytes | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.disk.{read,write,used,max}` | Disk I/O and capacity | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.network.{netin,netout}` | Network bytes | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.status` | Running state (1=running) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.qmp.status` | QMP status (1=running) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |
| `proxmox.vm.uptime` | VM uptime (seconds) | cluster, clusterid, node, nodeid, vmname, vmid, vmips |

### Container (LXC) metrics

| Key | Description | Dimensions |
|---|---|---|
| `proxmox.lxc.cpu.usage` | Container CPU usage | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.cpu.usable` | Container usable CPU count | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.memory.{mem,max}` | Memory bytes | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.swap.{usage,max}` | Swap bytes | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.disk.{read,write,usage,max}` | Disk I/O and capacity | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.network.{netin,netout}` | Network bytes | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.status` | Running state (1=running) | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |
| `proxmox.lxc.uptime` | Container uptime (seconds) | cluster, clusterid, node, nodeid, lxcname, lxcid, lxctype |

---

## 9. Topology model

Defined declaratively in [extension/extension.yaml](extension/extension.yaml) under `topology:`. Four custom entity types form a strict hierarchy:

```
proxmox:cluster
    └── proxmox:node
            ├── proxmox:vm
            └── proxmox:container
```

| Entity type | Display name | ID pattern | Primary source condition |
|---|---|---|---|
| `proxmox:cluster` | Cluster | `proxmox_cluster_{cluster}` | `$prefix(proxmox.cluster.)` (+ all other prefixes) |
| `proxmox:node` | Node | `proxmox_node_{cluster}_{node}` | `$prefix(proxmox.node.)` |
| `proxmox:vm` | Virtual Machine | `proxmox_vm_{cluster}_{node}_{vmid}` | `$prefix(proxmox.vm.)` |
| `proxmox:container` | Container | `proxmox_container_{cluster}_{node}_{lxcid}` | `$prefix(proxmox.lxc.)` |

All relationships use `RUNS_ON` (node runs on cluster; VM runs on node; container runs on node). Entities are *derived from metric dimensions* automatically — the extension never calls a topology API.

**Important:** the `proxmox:cluster` entity is synthesized from *every* metric prefix (`proxmox.cluster.*`, `proxmox.node.*`, `proxmox.vm.*`, `proxmox.lxc.*`) because every metric carries the `cluster` dimension. This means even if cluster-level API calls fail, the cluster entity will still appear if node or VM metrics are flowing.

Entity attributes (displayable properties in the Dynatrace UI) include:
- Cluster: `cluster` (name), `clusterid`
- Node: `cluster`, `clusterid`, `node` (name), `nodeip`, `nodeid`, `cpuinfo_cores`, `cpuinfo_sockets`
- VM: `cluster`, `clusterid`, `node`, `nodeip`, `vmid`, `vmname`, `vmips`
- Container: `cluster`, `clusterid`, `node`, `nodeip`, `vmid` (mapped from lxcid), `vmname` (mapped from lxcname)

---

## 10. Concurrency model

Three layers:

1. **EF2 scheduler** — each endpoint's `monitor` callback runs independently on its own cadence. Multiple endpoints can overlap.
2. **Inside `monitor`** — the cluster-level API calls (cluster/status and cluster/ha/status) run **sequentially** on the monitor thread before workers are submitted.
3. **Inside one cycle** — the five collection workers (`collect_nodes`, `collect_storage`, `collect_qemuvm`, `collect_lxc`, `collect_service`) all run **concurrently** via `ThreadPoolExecutor.submit`. They do not coordinate; they each independently iterate `node_info_list` and make their own API calls.

So for a cluster with 3 nodes and 10 running VMs, a single cycle issues roughly:
- 3 `GET nodes/{node}/status` (from collect_nodes, all concurrent across threads)
- 3 `GET nodes/{node}/storage` (from collect_storage)
- 3 `GET nodes/{node}/qemu` + up to 10 × `GET .../agent/network-get-interfaces` + 10 × `GET .../status/current` (from collect_qemuvm)
- 3 `GET nodes/{node}/lxc` + N × container status calls (from collect_lxc)
- 3 `GET nodes/{node}/services` (from collect_service)

The `ThreadPoolExecutor` has `max_workers=10`, which caps concurrent threads across all active endpoints. If many nodes and VMs are present, API calls within a single worker are still sequential (each worker loops over its list synchronously). Adding async within each worker would be an optimization path if API latency becomes a bottleneck.

---

## 11. Error handling

- **API call failures** — each `get_metrics` call is wrapped in a try/except. On exception, `JSON = json.dumps({})` is returned and the error is logged. Downstream `json.loads({})` in the collection methods will produce an empty dict, so metrics for that request are silently skipped. This is intentional — a single bad API call does not abort the cycle.

- **VM guest-agent failure** — the IP collection block in `collect_qemuvm` is wrapped in its own try/except. If the guest agent is not running, the exception is caught, a warning is logged, and `all_ips` stays as an empty string. Collection of the VM's other metrics continues normally.

- **`cluster_ha_info` not set** — if the cluster HA status API returns a non-list or contains no `quorum` entry, `cluster_ha_info` stays as the empty dict initialized before the if/else block. `.get("quorate")` and `.get("status")` on an empty dict return `None`, which will be sent as metric values. This is a known limitation — the extension does not skip the metric emission if HA info is missing.

- **`fastcheck`** — always returns `StatusValue.OK`. No preflight validation of the Proxmox connection or token is performed at activation time.

---

## 12. Design quirks and known tensions

A maintainer should know about these before touching the code:

1. **`verify_ssl=False` is hardcoded in `initialize`.** The `ProxmoxClient` constructor accepts `verify_ssl` as a parameter, but `initialize` always passes `False` ([proxmox/__main__.py:41](proxmox/__main__.py#L41)). There is no way for an operator to enable certificate verification without a code change.

2. **`host` is a list in the schema but only the first element is used.** `ProxmoxClient.__init__` logs a warning and coerces to a scalar. The schema's `maxObjects: 1` constraint keeps it to one entry, but the indirection still exists.

3. **`cluster_name` from config is never used in metrics.** The UI field is for human readability only. The actual cluster name in metric dimensions comes from the Proxmox API response (`cluster_status[type=="cluster"]["name"]`). If you want to override the cluster name in dimensions, there is currently no mechanism to do so.

4. **`initialize_proxmoxapi()` is called on every cycle.** A new `proxmoxer.ProxmoxAPI` object is created at the start of each `monitor` call. This is conservative but means an HTTPS handshake overhead on every poll. A persistent connection would be more efficient.

5. **Collection workers do not return errors to the caller.** The five `executor.submit()` calls are fire-and-forget — exceptions inside a worker are not re-raised in the main thread. If a worker crashes silently, its metrics simply stop appearing. Log inspection is the only way to detect this.

6. **`get_metrics_2` is a pass-through to `get_metrics`.** The two names exist because some call sites historically used one variant and some used the other. Both are now identical. If you need different behavior for sub-resource calls, this is where to diverge.

7. **Stopped VMs and containers are silently skipped.** Only `status == "running"` resources are collected. If a VM or container is stopped, you get no `proxmox.vm.*` or `proxmox.lxc.*` metrics for it — the entity may show as stale in the topology view. There is no explicit "offline" 0-metric emitted.

8. **`proxmoxtesting.py` is not production code.** It uses absolute imports (`from proxmox_testing_api import ProxmoxClient`) which only work when run directly from inside the `proxmox/` directory. It is not imported by the main module and is not bundled in the extension artifact.

---

## 13. Extension points

### Adding a new node-level metric

1. Identify the API field in the Proxmox response (check via `GET nodes/{node}/status` or the relevant resource).
2. Add the metric constant as a `report_metric` call inside `collect_nodes` (or the appropriate collector) in [proxmox/__main__.py](proxmox/__main__.py).
3. Register the metric in [extension/extension.yaml](extension/extension.yaml) under `metrics:` with the matching `dimensions:` list.
4. Add the key to the appropriate `featureSet` entry so it appears in the feature set grouping.

### Adding a new collection domain (e.g., cluster network)

1. Add a new `collect_<domain>` method to `ProxmoxExtension`, modeled on `collect_storage`.
2. Add an `executor.submit(self.collect_<domain>, endpoint, node_info_list, cluster_dimensions)` call in `monitor`.
3. Register all new metric keys in `extension.yaml`.
4. Add a new `featureSet` block if the domain is logically distinct enough to be selectively enabled.

### Adding support for `verify_ssl=True`

1. Add a boolean `verify_ssl` field to the endpoint schema in `activationSchema.json`.
2. Read it in `initialize` with `endpoint.get("verify_ssl", False)`.
3. Pass it through to `ProxmoxClient(verify_ssl=verify_ssl)`.
4. Remove the hardcoded `verify_ssl=False` in `initialize`.

---

## 14. Reference: file inventory

| File | Purpose |
|---|---|
| [proxmox/__main__.py](proxmox/__main__.py) | All production runtime logic. `ProxmoxExtension` class and `main()` entrypoint. |
| [proxmox/__init__.py](proxmox/__init__.py) | Empty package marker. |
| [proxmox/proxmox_api.py](proxmox/proxmox_api.py) | `ProxmoxClient` — wraps `proxmoxer.ProxmoxAPI` with JSON validation and error handling. |
| [proxmox/common_functions.py](proxmox/common_functions.py) | `common_functions.is_valid_json` — round-trip JSON validation used by the API client. |
| [proxmox/proxmox_testing_api.py](proxmox/proxmox_testing_api.py) | Extended `ProxmoxClient` for dev testing — adds cluster/node discovery helpers. Not used in production. |
| [proxmox/proxmoxtesting.py](proxmox/proxmoxtesting.py) | Standalone test script that exercises the API client directly. Not production code. |
| [extension/extension.yaml](extension/extension.yaml) | EF2 manifest: metrics, topology, feature sets, version, requirements. |
| [extension/activationSchema.json](extension/activationSchema.json) | UI configuration schema. |
| [extension/documents/proxmox_overview.dashboard.json](extension/documents/proxmox_overview.dashboard.json) | Built-in overview dashboard shipped with the extension. |
| [setup.py](setup.py) | Packaging; version is parsed from `extension.yaml`. |
| [activation.json](activation.json) | Local-dev shim for `dt-sdk run`. **Not** production config. |
| [secrets.json](secrets.json) | Local-dev placeholder. Don't put real secrets here. |
| [ruff.toml](ruff.toml) | Linter configuration. |
