# Configuration-Group Variable Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct BXT configuration-group variable declarations without changing the NaC module source or version.

**Architecture:** Templates remain the structural source, values remain per-device data, and `generate.py` remains the only writer of generated site data. `validate_model.py` provides an offline guard aligned to NaC 1.4.0 field names and provider constraints.

**Tech Stack:** Python 3, PyYAML, Terraform, netascode/nac-sdwan/sdwan 1.4.0.

---

### Task 1: Add offline regression checks

**Files:**
- Modify: `validate_model.py`

- [x] Resolve sites relative to the repository instead of a machine-specific path.
- [x] Reject `bgp_features[].neighbors`; require `ipv4_neighbors`.
- [x] Require `ipv4_address_type: static` on Ethernet interfaces using `ipv4_address_variable`.
- [x] Require `pseudo_commit_timer` as a config-group system variable and reject other unreferenced device-variable keys.
- [ ] Run the validator and confirm it fails on the current generated BXT data. Blocked because Python environment selection was declined.

### Task 2: Correct source templates and values

**Files:**
- Modify: `templates/branch/service.yaml`
- Modify: `templates/dc/service.yaml`
- Modify: `templates/branch/transport-a.yaml`
- Modify: `templates/branch/transport-b.yaml`
- Modify: `templates/dc/transport.yaml`
- Modify: `values/bxt.yaml`

- [x] Rename BGP `neighbors` collections to `ipv4_neighbors`.
- [x] Add static IPv4 address type to Ethernet interfaces with variable addresses.
- [x] Remove unused BXT device variables and add required `pseudo_commit_timer: 0` system variables.
- [x] Update nearby comments to explain the module/provider requirements.
- [x] Wire mandatory BGP `remote_as_variable` fields through active site values; retain `BGP_REMOTE_AS` as an explicit blocking placeholder.
- [x] Add mandatory default Global and OMP parcels to the shared system profile and enforce them in offline validation.

### Task 3: Regenerate and verify

**Files:**
- Regenerate: `sites/bxt/data/*`

- [ ] Run `generate.py --site bxt`.
- [ ] Run `validate_model.py` and expect success.
- [ ] Run `terraform validate` in `sites/bxt` and expect success.
- [ ] Run `terraform plan` only if credentials are present; never apply automatically.
- [x] Record current static verification evidence and execution blocker in the final report.
