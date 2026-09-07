# nac4 — Cisco Catalyst SD-WAN Network-as-Code

Manages a Cisco Catalyst SD-WAN fabric (vManage 20.13 / IOS-XE 17.13+) using
the `netascode/nac-sdwan/sdwan` Terraform module (v1.4.0), UX2 paradigm only.

---

## Sites

| Site | Role | Hardware | Variant | lab site_id |
|------|------|----------|---------|-------------|
| **BEL** | DC hub | C8500-12X pair | `dc` | 1 |
| **BXT** | Branch test-lab | C8200L pair | `branch-a-routed` | 3 |
| **CML** | Branch (internet-only) | VMs | `branch-b-routed` | 5 |

All three exist in vManage (applied 2026-09-04). No configuration has been
pushed to any device yet — `configuration_group_deploy` and
`policy_group_deploy` are `false` on all routers.

**BEL** is placeholder-blocked (chassis IDs, IPs, BGP AS unknown) — do not
deploy. **CML** still carries BXT's chassis IDs and IPs; real hardware values
are unknown.

---

## How it works

A single source of truth generates per-site Terraform roots:

```
globals.yaml          fabric-wide constants (NTP, DSCP, AS numbers, …)
templates/            YAML structure, one directory per variant
  _shared/            system, policy-objects, application-priority — all variants
  branch/             branch-a / branch-b service, transport, config-group, …
  dc/                 DC hub service, transport, CLI add-on, config-group, …
values/               one file per site — site_code, variant, site_id, device_variables
  aar/                per-site traffic policy (AAR + QoS, one file mandatory per site)
variants.yaml         maps each variant to the list of template files it uses
generate.py           renders templates/ + values/ → sites/<site>/data/*.yaml + .tf roots
validate_model.py     offline checks — run before every plan
```

`generate.py` substitutes `__SITE__` with the site code and `__GLOBAL:<key>__`
with the corresponding value from `globals.yaml`, then copies
`root-template/*.tf` into each site root. **Never edit files under `sites/`**
— they are overwritten on the next run.

```
sites/                GENERATED — gitignored, do not hand-edit
  bxt/
    data/*.yaml       rendered NaC YAML for this site
    main.tf
    providers.tf
    terraform.tfstate  state stays on the machine that ran apply
```

---

## Quick start

```bash
pip install -r requirements.txt

python3 generate.py                # regenerate all sites
python3 generate.py --site bxt     # regenerate one site
python3 generate.py --strict       # abort if any placeholder remains
python3 validate_model.py          # cross-checks — run before every plan

cd sites/bxt/
export SDWAN_URL=https://<vmanage>:<port>
export SDWAN_USERNAME=<user>
export SDWAN_PASSWORD=<password>
export SDWAN_INSECURE=true
terraform init
terraform plan -out=tfplan
# review the plan, then:
terraform apply tfplan
```

> **State warning**: `sites/` is gitignored. The Terraform state lives only on
> the machine that ran `apply` (the jump host, as of 2026-09-04). Running
> `terraform apply` from a stateless clone will attempt to recreate everything
> and fail on duplicate parcel names.

---

## Adding a site

1. Create `values/<site>.yaml` (pick a variant, assign a globally unique `site_id`).
2. Create `values/aar/<SITE>.yaml` (traffic policy — mandatory, `generate.py` aborts without it).
3. Run `python3 generate.py --site <site>` and `python3 validate_model.py`.
4. `cd sites/<site>/ && terraform init && terraform plan`.

---

## Key files

| File | Purpose |
|------|---------|
| `AGENTS.md` | Full design reference and hard rules for AI agents and operators |
| `UX2_PROJECT.md` | Project status — what is done, blocked, deferred |
| `globals.yaml` | Fabric-wide constants |
| `variants.yaml` | Maps variant names to their template file lists |
| `generate.py` | The generator — read its docstring for the full pipeline |
| `validate_model.py` | Offline validator — run before every `terraform plan` |
| `DATA/policies.json` | UX1 vManage export (migration reference) |
| `DATA/valid_conf/` | Anonymised UX1 device configs (diff target) |
| `DATA/generated_conf/` | Last known as-deployed config (bxtdw01, 2026-08-28) |
