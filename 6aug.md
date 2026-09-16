# Session handoff — 2026-08-06

## What was done today

All BGP redistribution + route-policy tasks from the SDD plan are complete:

| File | Change |
|---|---|
| `templates/_shared/system.yaml` | `advertise_ipv4_bgp: true` (BGP→OMP, all sites) |
| `templates/branch/service.yaml` | `ipv4_redistributes`, `propagate_community`, `send_community: both` |
| `templates/branch/service-routed.yaml` | Same BGP changes |
| `templates/dc/service.yaml` | Same BGP changes + comment on CLI linkage |
| `templates/dc/cli.yaml` | RT-POL-IN/OUT-BEL route-map blocks appended (PLACEHOLDER values) |
| `values/bel.yaml` | Commented `bgp_policy_in/out` activation block (both routers) |
| `templates/branch/cli.yaml` | **New** — branch CLI add-on skeleton (placeholder, no active config) |
| `variants.yaml` | **New** — extracted VARIANTS + SHARED_TEMPLATES from generate.py |
| `generate.py` | Loads variants.yaml at startup; branch/cli.yaml added to all 4 branch variants |
| `DEMO/edge-demo.yaml` | **New** — reference values for a branch BGP + route-map config (see below) |
| `SCHEMA-VALIDATION.md` | BGP service feature schema verified against NaC 1.4.0 |

Key schema findings (NaC 1.4.0, verified against `sites/bxt/.terraform/modules/sdwan/`):
- `ipv4_redistributes` (not `redistribute`)
- `propagate_community: true` works
- `fall_over_bfd` NOT in data model → CLI add-on only
- `route_policy_out_variable` does NOT exist — `route_policy_out` takes NaC feature name only, cannot reference CLI add-on route-maps

---

## Open question — tomorrow's work

**The problem:** `DEMO/edge-demo.yaml` was written with the neighbor linkage
(`neighbor X route-map Y out`) inside the CLI add-on block. The user wants it
separated: CLI add-on = route-map definition only; neighbor linkage = Terraform/variables.

**Why it's non-trivial:** `route_policy_out_variable` doesn't exist in NaC 1.4.0.
The `route_policy_out` field references only NaC-managed route policy features,
not CLI-defined route-maps. So there's no direct data-model path for this today.

**Three options analysed:**

**Option A — `{{varname}}` in CLI add-on string (recommended, verify first)**
vManage may resolve `{{varname}}` inside `cli_configuration` at device-attach time
(distinct from NaC's `_variable` field mechanism). If so:
- CLI add-on keeps only route-map definitions
- Neighbor linkage goes in CLI add-on with variable tokens:
  `neighbor {{bgp_neighbor_corp}} route-map {{bgp_route_map_out}} out`
- `bgp_neighbor_corp`, `bgp_neighbor_infra`, `bgp_route_map_out` become device variables
- Per-router IP difference is handled cleanly by device-variable substitution
- **Action: test with BXT — push a CLI add-on with `{{varname}}` and check what vManage sends to device**

**Option B — NaC route policy feature (fallback)**
Define the route-map as a NaC `sdwan_service_route_policy_feature` with device
variables for prefix-list name, metric, AS-path prepend. Then `route_policy_out`
in the neighbor can reference it by feature name.
- Fully Terraform-native
- Trade-off: route-map definition leaves the CLI add-on entirely; CLI add-on
  shrinks to only `fall-over bfd` / `distance bgp` / `always-compare-med`

**Option C — generate.py token substitution**
Add a `__VALUE:bgp_route_map_out__` token resolved from `values/<site>.yaml`
at generation time. Data-driven but generation-time only, not Terraform runtime.

---

## DEMO/edge-demo.yaml — what it shows

Target IOS-XE config: AS `10.10` (655370), router-id `10.99.209.17`, two neighbors
`10.0.0.1`/`10.0.0.2` (remote-as 65537), outbound route-map
`OMP_TO_BGP_1000_MED_ASPATH_PREPEND_BB` (metric 1000, AS-path prepend ×5 on specific
prefix, metric 1000 on all others), `fall-over bfd`, `distance bgp 20 200 20`,
`bgp always-compare-med`.

Layer 1 (device_variables → data model template):
- `bgp_as_number: '10.10'` — MUST be dotted; mismatch creates a second BGP process
- `bgp_router_id`, `bgp_neighbor_corp`, `bgp_neighbor_infra`, `bgp_neighbor_remote_as`
- Template emits: redistribute omp+connected, propagate_community, send_community both

Layer 2 (cli_addon block — currently includes neighbor linkage, pending tomorrow's fix):
- prefix-list `LO_BB_PFX` + route-map sequences
- `neighbor X fall-over bfd` + route-map linkage (linkage to move per above)
- `distance bgp 20 200 20`, `bgp always-compare-med`

---

## Repo state

- Branch: `master`
- Last commits: all above changes committed; run `git log --oneline -10` to verify
- BXT is live-deployed (`sites/bxt/terraform.tfstate` active)
- BEL is placeholder-blocked (never planned/applied)
- `generate.py --site bxt` regenerates BXT without touching other sites
