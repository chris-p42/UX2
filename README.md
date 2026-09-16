# nac4 — templated, generated, per-site NaC repo

Same fabric as `nac/`, `nac2/`, `nac3/` (originally scaffolded with 5
placeholder sites: `dc-hub`, `nyc`, `chicago`, `paris`, `london`; regions
`dc-hub`/`na`/`emea`), same underlying module
(`netascode/nac-sdwan/sdwan` 1.4.0). This layout is the one described in
`DESIGN.md` / `COMPARISON.md`: a single source of truth in `templates/` +
`values/`, distributed by `generate.py` into per-site, per-state Terraform
roots under `sites/` (generated, gitignored by default).

**Real sites (imported 2026-07 from UX1 vManage exports, see `UX1/`):**

| Site | Role | Variant | site_id | Hardware |
|------|------|---------|---------|----------|
| `BEL` (`values/bel.yaml`) | **The DC hub** | `dc` | 1100 | C8500-12X pair |
| `BXT` (`values/bxt.yaml`) | Branch test-lab | `branch-a` | 110 | C8200L pair |
| `CML` (`values/cml.yaml`) | branch-b design validation lab | `branch-b` | 3 | VMs (no 802.1Q trunk support) |

BXT's deployed lab site-id is **110** (moved from 3 on 2026-07-30 to free
that id for CML; the UX1 export historically used 1405 before that — that
number survives only in old template/export names). `generate.py` enforces
that the top-level `site_id` and every router's `device_variables.site_id`
agree, since the per-router value is what actually reaches the device
attach.

CML uses `branch-b` (no MPLS/TLOC-EXT) but keeps the same CORP+INFRA
dual-BGP-peer VPN10 model as branch-a, plus the user VLAN — the difference
is the LAN handoff: three untagged access ports (one per VLAN) instead of
one trunk, since CML's VMs can't do 802.1Q trunking. See
`templates/branch/service-b.yaml`. Not yet deployed.

The original 5 placeholder sites (fake IPs, site_ids 100–302) are parked
in `DEMO/` and ignored by `generate.py` — see `DEMO/README.md`.
`DEMO/dc-hub.yaml` is NOT the real DC — `BEL` is.

## ⚠️ Status of this scaffold

> **2026-07-29 update:** the caveats below are largely superseded. The
> templates were schema-validated against the real nac-sdwan 1.4.0 module
> source (see `SCHEMA-VALIDATION.md`) and **BXT is live-deployed** (config
> group + policy group created and applied against vManage, real chassis
> IDs in `values/bxt.yaml`). BEL remains placeholder-blocked (masks, IPs,
> chassis IDs, BGP AS) and has not been planned or applied.

This was built from the `COMPARISON.md`/`DESIGN.md` design docs alone — no
existing `nac4/` code, `nac/DESIGN.md` §2, `nac/README.md` §9, or
`nac/schema/sdwan.schema.json` was available. Concretely that means:

- The **overlay mechanism** (`generate.py`, the `templates/`+`values/` split,
  the per-site Terraform roots) is the real, working part — that's what
  `DESIGN.md` actually specifies.
- The **YAML content inside `templates/*.yaml`** (parcel key names, field
  shapes) is illustrative — built from general UX2/NaC conventions, not
  verified against your actual module schema. Every file has a `# TODO:
  verify against schema.json` marker at the parts most likely to need
  correcting. Run `terraform validate` (and your offline schema validator,
  once you point it at this repo) before trusting any of it.
- Site→variant assignment (which sites are `branch-a` vs `branch-b`) is a
  guess — confirm/fix in `values/*.yaml`.

## Layout

```
nac4/
├── generate.py              # the overlay — see its docstring
├── globals.yaml             # fabric-wide constants (NTP, DNS, DSCP, ...) — one source of truth
├── csv_to_values.py         # one-time migration: legacy variable CSV → values/*.yaml
├── requirements.txt
├── templates/
│   ├── _shared/              # system.yaml, policy.yaml — used by every variant
│   ├── branch/                # service, config-group, transport-a, transport-b
│   └── dc/                    # service, transport, cli, config-group
├── values/                   # one file per site: site_code, variant, site_id, device_variables
├── root-template/            # Terraform root files, copied as-is into every site
└── sites/                    # GENERATED — do not hand-edit, gitignored
    └── <site>/
        ├── data/*.yaml        # rendered NaC YAML for this site
        ├── main.tf
        └── providers.tf
```

## Global values (`globals.yaml`)

`templates/` already gives single-authoring for *structure* (edit a
template once, it applies to every site). `globals.yaml` does the same for
*values* that are identical fabric-wide (NTP servers, DNS, AAA order, DSCP
constants, banner text, ...): it's a plain YAML data file, no `__SITE__`
tokens, and templates reference it with `__GLOBAL:<dotted.key>__`, e.g.:

```yaml
ntp:
  servers: "__GLOBAL:ntp.servers__"
```

`generate.py` substitutes these at render time with the real value from
`globals.yaml`, type preserved — a list global comes back as a list, a
nested dict as a dict, not a stringified blob. Change a value once in
`globals.yaml`, re-run `generate.py`, it propagates to every site. An
unknown `__GLOBAL:...__` reference fails the generation immediately with a
clear error naming the missing key — it never falls back to a guess.

Only genuinely fabric-wide facts belong in `globals.yaml`. Anything
archetype-specific (a QoS value that differs for the DC hub, say) belongs
directly in `templates/dc/*.yaml` / `templates/branch/*.yaml` instead —
don't add a global just because two variants happen to currently agree.

## Workflow

```bash
pip install -r requirements.txt
python3 generate.py                # regenerate every site
python3 generate.py --site bxt     # regenerate just one

cd sites/bxt
export SDWAN_USERNAME=... SDWAN_PASSWORD=... SDWAN_URL=https://vmanage.example:8443
terraform init
terraform plan -out=tfplan
terraform apply tfplan             # only after reviewing the plan
```

Never hand-edit anything under `sites/` — edit `templates/` or `values/` and
re-run `generate.py`. If you want per-site PR diffs, remove `sites/` from
`.gitignore` and add a CI step that fails if `generate.py` produces a diff
against HEAD (a "regen is clean" check).

## Adding a 6th site

Add one file to `values/`, pick an existing `variant` (or add a new one to
the `VARIANTS` dict in `generate.py` plus its template files), assign a
globally-unique `site_id`, run `generate.py`.

## Changing something fabric-wide

Edit the relevant file in `templates/`, run `generate.py`, review each site's
plan individually before applying — a template change touches every site's
generated config but each site still applies independently (5 separate
`terraform apply`s, 5 separate blast radii).

## Open items to verify on a live vManage / against your schema

(carried over from `COMPARISON.md` — still open here)

- ~~`pseudo_commit_timer` semantics~~ — corrected by live validation
  2026-07-27: required as a config-group system device variable with value
  `0`, but it is not the deploy gate. Per-router deployment remains governed
  by `configuration_group_deploy` (see SCHEMA-VALIDATION.md §4).
- ~~TLOC-EXT field semantics~~ — schema-validated 2026-07-24
  (`tloc_extension` field on the WAN ethernet interface feature).
- Hub-and-spoke control topology — only QoS/AAR is modelled in
  `_shared/policy.yaml` so far.
- QoS DSCP classification — values must be decimal integers, never PHB
  keywords (EF=46, AF31=26, default=0).
- DC service-profile-without-interface (campus LAG is CLI add-on, no native
  UX2 LAG parcel — see `templates/dc/cli.yaml`).
- Lock files — `sites/` is gitignored by default, so `.terraform.lock.hcl`
  isn't committed; decide if you want to commit generated site dirs instead.
- Whether `netascode/nac-sdwan/sdwan` 1.4.0's actual YAML schema matches the
  key names used in `templates/` — check against
  `../nac/schema/sdwan.schema.json` once available.
