---
applyTo: "regions/**"
---

# Region authoring rules

## Core invariant — hard state isolation

State isolation operates at **two levels**:

- **Across regions**: `regions/na/` and `regions/emea/` never share a state
  file, lock file, or `terraform apply` invocation.
- **Within a region**: each branch site has its own sub-stack
  (`regions/na/nyc/`, `regions/na/chicago/`) with its own `terraform.tfstate`.
  A `terraform apply` in `nyc/` can never touch `chicago/` resources.

This is a load-bearing architectural requirement. Never collapse multiple sites
into one stack and never create a root-level `main.tf` spanning regions.

## Directory structure (per region)

```
regions/<name>/
├── policy/                    # ISOLATED STACK — regional policy only
│   ├── main.tf                # instantiates modules/policy-group; outputs policy_id
│   ├── variables.tf
│   ├── outputs.tf             # must output: policy_id
│   ├── terraform.tfvars       # gitignored — credentials
│   └── .terraform.lock.hcl
│
├── <site-a>/                  # ISOLATED STACK — one per branch site
│   ├── main.tf                # reads ../sites/<site>.yaml + policy_id from ../policy/
│   ├── variables.tf
│   ├── outputs.tf
│   ├── terraform.tfvars       # gitignored — credentials
│   └── .terraform.lock.hcl
│
├── <site-b>/                  # ISOLATED STACK — independent from <site-a>
│   └── (same structure)
│
├── sites/                     # YAML files only — NOT Terraform roots
│   ├── <site-a>.yaml
│   └── <site-b>.yaml
│
└── policy.yaml                # regional QoS + topology + app-route baseline
```

`regions/dc-hub/` keeps a **combined single stack** (policy + site together)
because there is only one hub site — splitting adds no benefit and the hub
is managed with extreme care regardless.

## Apply order within a region

1. `cd regions/<name>/policy && terraform apply` — must run first, or whenever
   `policy.yaml` or `modules/policy-group` changes. Branch site stacks read
   its output via `terraform_remote_state`.
2. `cd regions/<name>/<site> && terraform apply` — runs independently per site.
   No ordering constraint between sites.

Never apply a site stack before the policy stack has been applied at least once
in that region — the `terraform_remote_state` data source will fail if the
policy state file does not exist yet.

## Policy stack — main.tf pattern

```hcl
# regions/<name>/policy/main.tf
locals {
  globals = yamldecode(file("${path.module}/../../../globals.yaml"))
  policy  = yamldecode(file("${path.module}/../policy.yaml"))
}

module "regional_policy" {
  source      = "../../../modules/policy-group"
  region_name = "<name>"     # must match folder name and policy.yaml region: field
  policy_cfg  = local.policy
  dc_hub      = local.globals.dc_hub
}
```

```hcl
# regions/<name>/policy/outputs.tf
output "policy_id" {
  value = module.regional_policy.policy_id
}
```

## Site stack — main.tf pattern

```hcl
# regions/<name>/<site>/main.tf
locals {
  globals  = yamldecode(file("${path.module}/../../../globals.yaml"))
  site_cfg = yamldecode(file("${path.module}/../sites/<site>.yaml"))
  common = {
    aaa     = yamldecode(file("${path.module}/../../../common/aaa.yaml"))
    ntp     = yamldecode(file("${path.module}/../../../common/ntp.yaml"))
    banner  = yamldecode(file("${path.module}/../../../common/banner.yaml"))
    snmp    = yamldecode(file("${path.module}/../../../common/snmp.yaml"))
    logging = yamldecode(file("${path.module}/../../../common/logging.yaml"))
  }
}

data "terraform_remote_state" "policy" {
  backend = "local"
  config  = { path = "${path.module}/../policy/terraform.tfstate" }
}

module "site" {
  source             = "../../../modules/site"
  site_name          = "<site>"
  site_cfg           = local.site_cfg
  globals            = local.globals
  common             = local.common
  regional_policy_id = data.terraform_remote_state.policy.outputs.policy_id
}

module "policy_override" {
  count  = local.site_cfg.policy_override != null ? 1 : 0
  source = "../../../modules/policy-override"

  site_name       = "<site>"
  override_cfg    = local.site_cfg.policy_override
  config_group_id = module.site.config_group_id
}
```

Replace `<name>` and `<site>` with the actual region and site names.
`region_name` in the policy stack must match the folder name and `policy.yaml`'s
`region:` field — do not copy-paste without updating.

## Hub reference without shared state

Regional topology policies need the DC hub's identity (site-id, system IPs).
Regions must never manage the hub's resources.

Read the hub identity from `globals.yaml`, never duplicate or hardcode it:

```hcl
local.globals.dc_hub  # → { site_id, system_ip_a, system_ip_b }
```

Only `regions/dc-hub/` creates and manages the actual hub devices — every
other region treats this block as read-only reference data.

## policy.yaml schema

```yaml
region: na                          # must match the regions/<name>/ folder

qos:
  classes:
    - name: VOICE
      bandwidth_percent: 30
      dscp: 46                      # DECIMAL only — 46 = EF. Never PHB keywords.
    - name: BUSINESS_CRITICAL
      bandwidth_percent: 40
      dscp: 26                      # 26 = AF31
    - name: DEFAULT
      bandwidth_percent: 30
      dscp: 0                       # 0 = default/BE

topology:
  type: hub_and_spoke               # hub identity comes from globals.yaml dc_hub

app_route:
  sla_classes:
    - name: REALTIME
      loss_percent: 1
      latency_ms: 100
      jitter_ms: 20
    - name: TRANSACTIONAL
      loss_percent: 2
      latency_ms: 150
      jitter_ms: 30
```

**DSCP must be a decimal integer.** The provider rejects PHB keywords.
Decimal equivalents: EF=46, AF11=10, AF21=18, AF31=26, AF41=34, CS5=40,
CS6=48, default/BE=0.

## What changes propagate where

- **`policy.yaml` change** → affects `policy/` stack only. Branch site stacks
  read the policy ID as data — they do not re-apply the policy. Re-applying
  the policy stack is sufficient.
- **`modules/policy-group` change** → same as above; only `policy/` stack needs
  re-apply.
- **`modules/*` change (any other module)** → affects every site stack that uses
  the module. Call this out to the user before proceeding.
- **Site YAML change** → affects only that site's stack.
- **`common/*.yaml` change** → affects every site stack on their next apply
  (system profile parcels). Call this out to the user.

## Commands

```bash
# Policy stack — run first, or on policy.yaml changes
cd regions/na/policy
terraform init -upgrade
terraform plan -out=tfplan
terraform apply tfplan

# Site stack — independent per site
cd regions/na/nyc
terraform init -upgrade
terraform plan -out=tfplan
terraform apply tfplan

# Format everything (run from repo root to also catch modules/)
terraform fmt -recursive

# Validate a site stack
cd regions/na/nyc
terraform validate

# State inspection
terraform state list
terraform state show 'module.site.module.config_group.sdwan_configuration_group.this'
```

## Hard rules

- Never run `terraform apply` without showing the plan and waiting for approval.
- Never use `terraform taint` or `terraform state rm` without explicit user approval.
- Never add a remote or shared backend spanning multiple regions or sites —
  local backend only, one `terraform.tfstate` per sub-stack directory.
  `terraform_remote_state` within the same region (policy → site) is permitted.
- Never commit `terraform.tfvars`, `*.tfstate`, or `.terraform/` — all gitignored.
- Never let `regions/dc-hub/` be modified as a side effect of a regional change.
- Apply the `policy/` stack before any site stack in a new region — the remote
  state data source fails if the policy state file does not yet exist.
- `terraform fmt -recursive` from inside a sub-stack only formats that directory.
  Run from the repo root to also format `modules/`.
