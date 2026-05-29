# Proxmox VE Monitoring Extension

A Dynatrace Extensions 2.0 (EF2) Python extension that provides **full-stack monitoring** for Proxmox Virtual Environment clusters. It connects to the Proxmox REST API via token-based authentication and emits metrics for clusters, nodes, storage, QEMU virtual machines, LXC containers, and node services.

| | |
|---|---|
| **Extension ID** | `custom:com.dynatrace.proxmox-topomaping` |
| **Module** | `proxmox` |
| **Framework** | Dynatrace Extensions 2.0 (Python) |
| **Min. Dynatrace** | 1.908.0 |
| **Min. EEC** | 1.313.0 |
| **Python** | ≥ 3.10 |
| **Platform** | Remote or Local (EEC or OneAgent host) |

---

## What it monitors

Every poll cycle (default: 60 seconds per endpoint) the extension collects metrics across six domains:

| Domain | Feature Set | Metrics collected |
|---|---|---|
| Cluster | `Cluster` | Total nodes, online nodes, HA quorate, HA status, SDN status |
| Node | `Node` | CPU usage/wait/idle, memory, swap, rootfs, load average, uptime, online status, VM count, LXC count |
| Node Storage | `Node-Storage` | Total, used, available capacity per active storage volume |
| Node Services | `Node-Services` | Running state, active-state, and unit-state per systemd service |
| QEMU VMs | `VM` | CPU, memory (with balloon), disk I/O, network I/O, QMP status, IP addresses, uptime |
| LXC Containers | `CONTAINER` | CPU, memory, swap, disk I/O, network I/O, status, uptime |

A complete topology of `cluster → node → vm / container` is synthesized from the metric dimensions and rendered as native Dynatrace entities.

---

## Documentation

The full doc set is split by audience:

| Document | Audience | Purpose |
|---|---|---|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Engineers maintaining or extending the code | Deep-dive into internal mechanics: runtime model, API client design, execution flow, concurrency model, metric and topology model, and known design quirks. **Start here if you're modifying the extension.** |
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Operators rolling the extension out to a tenant | Step-by-step install guide: prerequisites, Proxmox token setup, signing, upload, monitoring configuration, validation, and a diagnostic table for common deployment failures. **Start here if you're shipping it.** |
| **[KNOWLEDGE_TRANSFER.md](KNOWLEDGE_TRANSFER.md)** | New team members getting onboarded | Broad-scope reference covering purpose, repo layout, configuration fields, metrics catalogue, topology catalogue, alerts, and glossaries for both Proxmox and Dynatrace EF2 terminology. Use it as a reference handbook. |

---

## Quickstart for developers

For a real install, follow [DEPLOYMENT.md](DEPLOYMENT.md) — the steps below are for local development only.

```bash
# 1. Install in editable mode
pip install -e ".[dev]"

# 2. Edit activation.json with your Proxmox host IP, user, and API token

# 3. Run a single simulated cycle against your environment
dt-sdk run

# 4. Build a release artifact (after bumping version in extension/extension.yaml)
dt-sdk build .
dt-sdk sign dist/*.zip
dt-sdk upload dist/*.zip --url https://<tenant>.live.dynatrace.com --api-token <token>
```

---

## Repository layout

```
EF2-Python-Proxmox/
├── proxmox/
│   ├── __init__.py                 ← empty marker file
│   ├── __main__.py                 ← all runtime logic (~680 lines)
│   ├── proxmox_api.py              ← ProxmoxClient wrapper around proxmoxer
│   ├── common_functions.py         ← JSON validation utility
│   ├── proxmox_testing_api.py      ← extended client used by the test script
│   └── proxmoxtesting.py           ← standalone dev/test script (not production)
├── extension/
│   ├── extension.yaml              ← EF2 manifest: metrics, topology, version
│   ├── activationSchema.json       ← UI configuration schema
│   └── documents/
│       └── proxmox_overview.dashboard.json  ← built-in overview dashboard
├── setup.py                        ← packaging (version parsed from extension.yaml)
├── ruff.toml                       ← linter config
├── activation.json                 ← local dev shim for `dt-sdk run` — NOT production
├── secrets.json                    ← local dev placeholder — do NOT put real values here
├── README.md                       ← this file
├── ARCHITECTURE.md                 ← internal mechanics
├── DEPLOYMENT.md                   ← install & rollout guide
└── KNOWLEDGE_TRANSFER.md           ← onboarding reference
```

---

## Heads-up for operators

Two things are worth knowing before deploying:

1. **SSL verification is hardcoded to `False`.** The `ProxmoxClient` always passes `verify_ssl=False` regardless of environment. This is intentional for self-hosted Proxmox environments that typically use self-signed certificates, but it means TLS certificate validation is not enforced. Plan to address this if your security policy requires it.

2. **VM IP collection requires the QEMU guest agent.** The extension calls the Proxmox guest-agent API (`/agent/network-get-interfaces`) to retrieve VM IP addresses. If the guest agent is not installed and running inside a VM, the IP dimension will be blank for that VM — the extension logs a warning and continues. This does not affect any other metric.

---

## License

See [LICENSE](LICENSE).
