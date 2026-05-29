# Deployment & Install Guide — Proxmox VE Monitoring Extension

**Audience:** the engineer or operator deploying this extension into a Dynatrace tenant for the first time (or a new tenant).
**Outcome after following this guide:** a signed extension uploaded to the tenant, an active monitoring configuration, and at least one datapoint visible in Data Explorer for each metric family.

For internal mechanics see [ARCHITECTURE.md](ARCHITECTURE.md). For the project overview and configuration reference see [KNOWLEDGE_TRANSFER.md](KNOWLEDGE_TRANSFER.md).

---

## Table of contents

1. [Deployment overview](#1-deployment-overview)
2. [Prerequisites](#2-prerequisites)
3. [Proxmox API token setup](#3-proxmox-api-token-setup)
4. [Signing certificate setup](#4-signing-certificate-setup)
5. [Build the extension](#5-build-the-extension)
6. [Sign the artifact](#6-sign-the-artifact)
7. [Upload to the Dynatrace tenant](#7-upload-to-the-dynatrace-tenant)
8. [Activate and create a monitoring configuration](#8-activate-and-create-a-monitoring-configuration)
9. [Validation: confirm metrics are flowing](#9-validation-confirm-metrics-are-flowing)
10. [Common deployment failures](#10-common-deployment-failures)
11. [Upgrades and rollbacks](#11-upgrades-and-rollbacks)
12. [Pre-deployment checklist](#12-pre-deployment-checklist)

---

## 1. Deployment overview

```
+----------------+   build    +-------------+   sign    +-------------+
| Source repo    +----------->+ unsigned    +---------->+ signed      |
| (this folder)  | dt-sdk     | .zip in     | dt-sdk    | .zip in     |
|                |            | dist/       |           | dist/       |
+----------------+            +-------------+           +------+------+
                                                               |
                                                               | upload
                                                               v
+---------------------------+      activate      +-------------+--------+
| EEC host                  |<-------------------+ Dynatrace tenant     |
|  - Python 3.10+           |                    |  - extension registry|
|  - network to Proxmox     |                    |  - monitoring config |
|    port 8006              |                    |  - metric ingest     |
+---------------------------+                    +----------------------+
                                                               ^
                                                               |
                                                               | report_metric
                                                               |
                                                  +------------+------------+
                                                  | running extension       |
                                                  | (one schedule per       |
                                                  |  endpoint)              |
                                                  +-------------------------+
```

The deployment has two halves that must both be in place before the first datapoint appears:

1. **Tenant side** — the signed `.zip` is uploaded, the extension's signing CA is trusted, the extension is activated, and a monitoring configuration is created.
2. **EEC side** — the EEC has Python 3.10+, the `proxmoxer` dependency, and network reachability to the Proxmox cluster on port 8006.

Skipping either half produces a silently-broken deployment: the extension appears "active" in the UI but emits no metrics.

---

## 2. Prerequisites

### Tenant

| Requirement | Source / how to verify |
|---|---|
| Dynatrace tenant version ≥ **1.908.0** | `extension.yaml: minDynatraceVersion` |
| **Extension Execution Controller (EEC)** ≥ **1.313.0** running on an ActiveGate | `extension.yaml: minEECVersion` |
| API token with scopes: **`extensions.write`**, **`extensionConfigurations.write`**, **`extensionEnvironment.write`** | Settings → Access Tokens |
| Extension signing CA installed in tenant trust store | Settings → Credential Vault → Extension signing CA — see [Section 4](#4-signing-certificate-setup) |

### Build host (where you run `dt-sdk`)

| Requirement | Notes |
|---|---|
| Python **≥ 3.10** | `setup.py` enforces this. |
| `pip install "dt-extensions-sdk[cli]"` | Install the EF2 build/sign/upload toolchain. |
| Access to the signing certificate + private key | Paths are in `.vscode/settings.json`. See [Section 4](#4-signing-certificate-setup). |
| The full repo (this folder) | Specifically `extension/`, `proxmox/`, `setup.py`. |

### EEC host

| Requirement | Notes |
|---|---|
| Python ≥ 3.10 already available to the EEC runtime | Verified by the EEC version requirement above. |
| `proxmoxer` and `requests` Python packages | These are declared in `setup.py` and are installed automatically when the extension is deployed. No manual installation needed. |
| Network egress from EEC to the Proxmox master node on **port 8006** (HTTPS) | The Proxmox REST API runs on port 8006. Verify with `curl -k https://<proxmox-host>:8006/api2/json` from the EEC host. |
| No certificate validation requirement | SSL verification is currently hardcoded to `False`. See [ARCHITECTURE.md §12](ARCHITECTURE.md#12-design-quirks-and-known-tensions). |

---

## 3. Proxmox API token setup

The extension authenticates using a **Proxmox API token** (not a username and password). API tokens are scoped, revocable, and do not expire with password rotations.

### 3.1 Create a dedicated monitoring user (recommended)

In the Proxmox web UI:

1. **Datacenter → Users → Add**
2. Username: `dtmonitoring` (or your preferred naming convention)
3. Realm: `pam` (or `pve` if using Proxmox's own auth)
4. Uncheck "Expire" — monitoring accounts should not expire

### 3.2 Assign the required permissions

The monitoring user needs **read-only** access. In **Datacenter → Permissions → Add → User Permission**:

| Path | User | Role |
|---|---|---|
| `/` (root) | `dtmonitoring@pam` | `PVEAuditor` |

The `PVEAuditor` role grants read access to all cluster, node, VM, container, storage, and service APIs. It does not allow any modifications.

> If you want tighter scoping, create a custom role with only the following privileges: `Sys.Audit`, `VM.Audit`, `Datastore.Audit`. However, the standard `PVEAuditor` role is the simplest correct choice.

### 3.3 Create the API token

In **Datacenter → Users → Select the monitoring user → API Tokens → Add**:

| Field | Value |
|---|---|
| Token ID | `dynatrace` (or any name — this becomes `token_name` in the extension config) |
| Privilege Separation | **Unchecked** — the token inherits the user's permissions |
| Expire | `Never` (or set a rotation schedule) |

Copy the token secret immediately after creation — Proxmox **will not show it again**.

The full credential used by `proxmoxer` is `dtmonitoring@pam!dynatrace:<token_secret>`.

### 3.4 Verify the token works

From the EEC host or any host with network access to Proxmox:

```bash
curl -k -H "Authorization: PVEAPIToken=dtmonitoring@pam!dynatrace:<token_secret>" \
  https://<proxmox-host>:8006/api2/json/cluster/status
```

A successful response returns a JSON array with cluster and node entries. If you see a `401 Unauthorized`, the token or permissions are wrong.

---

## 4. Signing certificate setup

EF2 Python extensions must be signed. The tenant trusts a CA; you sign with a developer certificate chained to that CA.

### 4.1 Locate (or generate) the signing material

This repo's `.vscode/settings.json` points at a dev cert pair. Check the current paths there. If the cert pair doesn't match the CA uploaded to your target tenant:

```bash
dt-sdk genca           # one-time per CA — generates ca.pem + ca.key
dt-sdk gendevcert      # one developer cert per engineer — generates dev.pem + dev.key
```

The CA's public `.pem` must be uploaded to the tenant's **Settings → Credential Vault → Extension signing certificates** before any extension signed by it can be uploaded.

### 4.2 Confirm the CA is trusted by the target tenant

In the tenant UI: **Settings → Credential Vault → Extension signing certificates**. The CA you will sign with must appear in this list. If it doesn't, upload it first; otherwise `dt-sdk upload` rejects the artifact with `signature verification failed`.

---

## 5. Build the extension

```bash
cd <repo-root>
dt-sdk build .
```

The build:
- Reads `extension/extension.yaml` for the version.
- Bundles the `proxmox/` package (declared in `extension.yaml` as `python.runtime.module: proxmox`).
- Writes an **unsigned** `.zip` into `dist/`:

  ```
  dist/custom_com.dynatrace.proxmox-topomaping-<version>.zip
  ```

### Bumping the version before a build

The tenant **refuses** to overwrite an existing version. Before every build that produces a release artifact, bump `version` in [extension/extension.yaml](extension/extension.yaml):

```yaml
version: 0.1.4   # was 0.1.3
```

`setup.py` reads the version from the same file, so there is only one source of truth.

A failed upload due to an existing version number is the single most common build-time mistake. If you forget, the upload step in Section 7 fails with a clear `extension version already exists` error.

---

## 6. Sign the artifact

```bash
dt-sdk sign dist/custom_com.dynatrace.proxmox-topomaping-<version>.zip
```

`dt-sdk` reads the cert/key paths from `.vscode/settings.json` (or from a `.dt-sdk.toml` if you maintain one). Output is a signed `.zip` ready to upload.

Build and sign in one shell:

```bash
dt-sdk build . && dt-sdk sign dist/*.zip
```

---

## 7. Upload to the Dynatrace tenant

```bash
dt-sdk upload dist/custom_com.dynatrace.proxmox-topomaping-<version>.zip \
  --url https://<tenant>.live.dynatrace.com \
  --api-token <token>
```

What the tenant does:
1. Verifies the artifact's signature against installed CAs.
2. Validates `extension.yaml` against the platform schema (metric keys, topology rules, `minDynatraceVersion`).
3. Registers the new version. **It is not active yet** — see next section.

### Upload error → meaning

| Error fragment | What it usually means |
|---|---|
| `signature verification failed` | The signing CA is not in the tenant's trust store. Re-do [Section 4](#4-signing-certificate-setup). |
| `extension version already exists` | Bump the version in `extension.yaml` and rebuild. |
| `schema validation failed: ...` | A metric, topology, or activation-schema field is malformed. The error message usually points at the specific section. |
| `unsupported tenant version` | Your tenant is older than `minDynatraceVersion: 1.908.0`. |

---

## 8. Activate and create a monitoring configuration

In the Dynatrace tenant UI:

### 8.1 Activate the version

**Hub → Manage extensions → custom:com.dynatrace.proxmox-topomaping → Activate**, then pick the version you just uploaded. Older versions remain available for rollback.

### 8.2 Add a monitoring configuration

Click **Add monitoring configuration** and select the **ActiveGate group** running your EEC. This binds the extension to the host that has network access to Proxmox.

Then click **Add endpoint** and fill in:

| Field | Required value |
|---|---|
| Cluster name | A friendly label (e.g. `PROD`). Shown in the UI summary; not used in metric dimensions. |
| Host IP Address | The IP address of the Proxmox master cluster node (e.g. `192.168.1.10`). |
| User Name | The Proxmox user created in [Section 3.1](#31-create-a-dedicated-monitoring-user-recommended) (e.g. `dtmonitoring@pam`). |
| Token Name | The token ID from [Section 3.3](#33-create-the-api-token) (e.g. `dynatrace`). |
| Token Value | The token secret copied at creation time. Stored encrypted in the tenant. |
| Frequency | `60` seconds is the default. Reduce only if higher-resolution data is required. |

### 8.3 Save

The monitoring configuration starts running on its next polling tick (within `frequency` seconds). The first full cycle takes one `frequency` interval to complete.

---

## 9. Validation: confirm metrics are flowing

After the first poll cycle should have completed (default: ~60 seconds):

### 9.1 In the Dynatrace UI

**Data Explorer → Search metrics → `proxmox`** — you should see datapoints for at least:

- `proxmox.cluster.node`
- `proxmox.cluster.ha.status`
- `proxmox.node.cpu.usage`
- `proxmox.node.memory.used`
- `proxmox.vm.cpu.usage` (if running VMs exist)
- `proxmox.lxc.cpu.usage` (if running containers exist)

### 9.2 In the EEC logs

On the EEC host, check the extension log:

```bash
sudo tail -F /var/log/dynatrace/extensions/<extension-pod>/*.log
```

A healthy cycle logs lines like:

```
Collected cluster level status info: [...]
Sent to metrics server for cluster: <cluster-name> with dimensions: {...}
Sent to metrics server for node: <node-name> with dimensions: {...}
Sent to metrics server for storage: <storage-name> for node: <node-name> with dimensions: {...}
Sent to metrics server for VM: <vm-name> for node: <node-name> with dimensions: {...}
```

If you see `Error fetching metrics for '...'`, the API call is failing — check network connectivity and token permissions.

### 9.3 In the topology view

Within ~5 minutes the topology entities (`proxmox:cluster`, `proxmox:node`, `proxmox:vm`, `proxmox:container`) should appear. Browse to **Infrastructure → Custom entities** or search by entity type. If cluster and node entities appear but VM/container entities are missing, those workloads may not be running — verify by checking `proxmox.node.vm` and `proxmox.node.lxc` metrics.

---

## 10. Common deployment failures

| Symptom | Likely cause | Fix |
|---|---|---|
| 1. Upload rejected: `signature verification failed` | Tenant doesn't trust the signing CA. | Upload the CA `.pem` to **Settings → Credential Vault → Extension signing certificates**. |
| 2. Upload rejected: `extension version already exists` | Forgot to bump `version` in `extension.yaml`. | Bump and rebuild. |
| 3. Extension is active but no metrics appear | The EEC host cannot reach Proxmox on port 8006. | Run `curl -k https://<proxmox-host>:8006/api2/json` from the EEC host. Check firewall rules. |
| 4. Metrics appear but the cluster has wrong name/dimensions | The cluster name in dimensions comes from the Proxmox API, not the `Cluster name` field in the UI config. | The API-returned cluster name is authoritative. Verify via `GET cluster/status`. |
| 5. `Error fetching metrics for 'cluster/ha/status/current'` in logs | HA is not configured on this Proxmox cluster. | This API endpoint returns an error on clusters without HA enabled. The extension will log an error and report empty HA metrics. This is cosmetic — other metrics are unaffected. |
| 6. VM `vmips` dimension is always empty | The QEMU guest agent is not running inside the VM. | Install and start `qemu-guest-agent` inside each VM you want IP tracking for. See [README.md §Heads-up](README.md#heads-up-for-operators). |
| 7. Token auth fails with `401 Unauthorized` | Wrong token name, wrong token value, or wrong user format. | Verify with the `curl` command in [Section 3.4](#34-verify-the-token-works). Ensure user format is `user@realm` (e.g. `root@pam`). |
| 8. Storage metrics missing for some volumes | Only `active == 1 AND enabled == 1` storages are collected. | Check storage status in Proxmox UI: **Datacenter → Storage**. Inactive or disabled storages are intentionally skipped. |
| 9. Node service metrics are absent | The Proxmox API for services (`/nodes/{node}/services`) requires at least `Sys.Audit` privilege. | Verify the monitoring user has `PVEAuditor` or `Sys.Audit` on `/`. |
| 10. `proxmox.cluster.sdn.status` is always `1` even when SDN has issues | If no SDN entries are returned by the API, `sdn_status` defaults to `1`. | Verify SDN configuration in Proxmox and check the raw API response via `curl`. |

---

## 11. Upgrades and rollbacks

### Upgrade

1. Make the code change.
2. **Bump `version`** in [extension/extension.yaml](extension/extension.yaml).
3. `dt-sdk build . && dt-sdk sign dist/*.zip && dt-sdk upload ...`.
4. In the tenant UI, the new version appears. **Activate** it. Existing monitoring configurations migrate automatically as long as the activation schema is backwards-compatible (add new optional fields with defaults; do not remove or rename existing fields).
5. Watch a poll cycle in the EEC log to confirm the new version is live.

### Rollback

In **Hub → Manage extensions → custom:com.dynatrace.proxmox-topomaping → Versions**, click the previous version → **Activate**. The monitoring configuration switches over on the next poll. No `.zip` rebuild needed.

### Activation schema changes

- **Adding** a new optional field with a `default`: safe. Existing configurations pick up the default.
- **Removing** a field: existing configurations may break. Bump version and notify operators.
- **Renaming**: equivalent to remove + add. Avoid unless necessary.

---

## 12. Pre-deployment checklist

### Build host
- [ ] Repo cloned, current branch matches what you intend to deploy
- [ ] `version` in `extension/extension.yaml` is **higher than** the highest version already in the tenant
- [ ] Signing certificate paths in `.vscode/settings.json` match the CA trusted by the target tenant
- [ ] `dt-sdk build .` succeeds with no schema warnings

### Tenant
- [ ] Tenant version ≥ 1.908.0
- [ ] EEC version ≥ 1.313.0 on the selected ActiveGate
- [ ] Signing CA is in **Settings → Credential Vault → Extension signing certificates**
- [ ] API token has `extensions.write`, `extensionConfigurations.write`, `extensionEnvironment.write`

### Proxmox
- [ ] Monitoring user created with `PVEAuditor` role at `/`
- [ ] API token created and secret copied
- [ ] Token verified via `curl` from the EEC host (port 8006 reachable, 200 OK)
- [ ] (Optional) QEMU guest agent running in VMs where IP tracking is required

### Post-deployment
- [ ] Data Explorer shows datapoints under `proxmox.*`
- [ ] Topology entities (`proxmox:cluster`, `proxmox:node`) appear within ~5 minutes
- [ ] EEC log shows clean `Sent to metrics server for cluster: ...` lines
- [ ] Spot-check node CPU, memory, and at least one VM metric
