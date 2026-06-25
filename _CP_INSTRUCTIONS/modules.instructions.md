---
applyTo: "modules/**/*.tf"
---

# Module authoring rules

## Structure

Every module must contain:
- `main.tf` — resource definitions only
- `variables.tf` — all input variable declarations with `description` and `type`
- `outputs.tf` — at minimum `config_group_id` (string) and `device_ids` (list of strings)

## UX2 resource types to use

| Purpose | Resource |
|---|---|
| Config group | `sdwan_configuration_group` |
| Transport feature profile | `sdwan_transport_feature_profile` |
| Service feature profile | `sdwan_service_feature_profile` |
| System feature profile | `sdwan_system_feature_profile` |
| **OMP settings** (device-wide, module/site) | `sdwan_system_omp_feature` — `advertise_ipv4_bgp` is the BGP→OMP direction, confirmed flat/global, NOT per-VPN |
| WAN ethernet interface parcel | `sdwan_transport_wan_vpn_interface_ethernet_feature` |
| **VPN 0 container** (transport-side, module/transport) | `sdwan_transport_wan_vpn_feature` |
| **VPN 10+ container** (service-side, module/service) | `sdwan_service_lan_vpn_feature` (valid range 1–65527 — never use for VPN 0) |
| **VPN 10+ BGP** (service-side, module/service) | `sdwan_service_routing_bgp_feature` — `omp` valid here for OMP→BGP only |
| OSPF parcel (service-side) | `sdwan_service_routing_ospf_feature` |
| OSPF parcel (transport-side, `private1` underlay) | `sdwan_transport_routing_ospf_feature` — one per transport feature profile; created when any transport entry has an `ospf` block |
| Prefix list (route-map match) | `sdwan_policy_object_prefix_list` |
| Route-map parcel | `sdwan_service_route_policy_feature` (service-side) / `sdwan_transport_route_policy_feature` (transport-side) |
| **CLI add-on profile** (UX2 escape hatch) | `sdwan_cli_feature_profile` — profile container |
| **CLI add-on parcel** (raw IOS-XE CLI) | `sdwan_cli_config_feature` — parcel inside CLI profile |
| Topology policy | `sdwan_centralized_policy` |
| App-route policy definition | `sdwan_application_aware_routing_policy_definition` |
| Device attach | `sdwan_attach_feature_device_template` |

Never use `sdwan_feature_template`, `sdwan_cli_template_feature_template`, or
`sdwan_cli_device_template` — all three are UX1 constructs. The UX2 CLI
add-on uses `sdwan_cli_feature_profile` + `sdwan_cli_config_feature` only.

## Device attach — mandatory variables

Every device attach (`sdwan_attach_feature_device_template` or config-group
attach) MUST include `pseudo_commit_timer = 300` in its variables map. The
attach fails without it, and it's easy to miss because it maps to no per-site
YAML field. Implement it as a constant in the attach resource, or as a module
variable `pseudo_commit_timer` defaulting to `300`, applied to every device
attach for every site and region. Do NOT expose it as a per-site YAML field —
it's the same value everywhere; baking it into the module guarantees it's
never forgotten when a new site is added.

## DSCP format

Any DSCP value (QoS classes, policy_override.qos, app-route marking) is a
**decimal integer**, never a PHB keyword. The provider rejects `ef`, `af31`,
`cs5`, `default`, etc. Decimal map: EF=46, AF11=10, AF21=18, AF31=26, AF41=34,
CS5=40, CS6=48, default/BE=0. If incoming YAML carries a keyword, convert to
decimal before passing to the resource — never pass the keyword through.

**Critical: VPN 0 is never service-side.** `sdwan_service_lan_vpn_feature`
rejects VPN 0 outright (valid range starts at 1) because VPN 0 is the
transport VPN. Any `service_vpns` entry where `vpn == 0` must be built by
`modules/transport` using `sdwan_transport_wan_vpn_feature` +
`sdwan_transport_routing_bgp_feature`, attached to the same shared
transport profile `modules/transport` and `modules/tloc-ext` already use.
Only entries with `vpn >= 1` (e.g. VPN 10) go through `modules/service`.
`modules/site` is responsible for routing each `service_vpns` entry to the
correct module based on its `vpn` value — never let `modules/service`
receive a VPN 0 entry.

## modules/system-profile

Instantiated once per site inside `modules/site`. Creates the system feature
parcels that apply to both cEdges: AAA/TACACS, NTP, Banner, SNMP, Logging.

Accepts two inputs:
- `var.common` — the merged `common/` YAML map loaded in the site stack's
  `locals` block (keys: `aaa`, `ntp`, `banner`, `snmp`, `logging`)
- `var.system_overrides` — the `system:` block from the site YAML (may be
  null for fields the site does not override)

The module deep-merges common values with site overrides. Site-level values
win on conflict. Merge pattern:

```hcl
locals {
  snmp = merge(var.common.snmp, try(var.system_overrides.snmp, {}))
}
```

Resources to create:

| Parcel | Resource |
|---|---|
| AAA / TACACS | `sdwan_system_aaa_feature` |
| NTP | `sdwan_system_ntp_feature` |
| Banner | `sdwan_system_banner_feature` |
| SNMP | `sdwan_system_snmp_feature` |
| Logging | `sdwan_system_logging_feature` |

TACACS key/secret must come from a `sensitive = true` Terraform variable —
never from the common YAML or site YAML (credentials are not in YAML files).

## modules/policy-group vs modules/policy-override

These are two distinct modules with different instantiation scope — do not
conflate them:

- **`modules/policy-group`**: instantiated **once per region**, in that
  region's `main.tf`. Builds the shared `sdwan_centralized_policy`
  (hub-and-spoke topology), QoS classes, and
  `sdwan_application_aware_routing_policy_definition` from the region's
  `policy.yaml`. The hub identity for the topology definition comes from
  `var.dc_hub` (passed in from `globals.yaml`'s `dc_hub` block) — never
  hardcode hub site-id or system IPs inside this module.
- **`modules/policy-override`**: instantiated **per site, only when that
  site's `policy_override` is non-null**. Creates additional localized
  parcels (QoS class override, app-route SLA override) attached to that
  specific site's config group. Must never create a new
  `sdwan_centralized_policy` — it only adds parcels on top of the existing
  regional policy referenced by `regional_policy_id`.

## Campus peering — VPN 10 only, two-VRF trunk

VPN 0 has **no campus peering**. It is transport underlay only — route its
`service_vpns` entry to `modules/transport` to create the VPN 0 container
(`sdwan_transport_wan_vpn_feature`) and nothing else. `sdwan_transport_routing_bgp_feature`
is not used in this design.

VPN 10 is the sole service VPN with campus peering. Its campus trunk carries
two VRFs (CORP and INFRA), each mapped to a dedicated VLAN/SVI on the campus
L3 switch. Never route a `vpn == 0` entry into `modules/service` —
`sdwan_service_lan_vpn_feature` rejects VPN 0 outright.

The campus peering protocol is **BGP or OSPF**, chosen per cEdge via a `bgp`
or `ospf` sub-block on each `cedge_a`/`cedge_b` entry. Exactly one is
non-null; the other is `~`. Branch on `cedge.bgp != null` to select the
resource type:

- `cedge.bgp != null` → create `sdwan_service_routing_bgp_feature`
- `cedge.ospf != null` → create `sdwan_service_routing_ospf_feature`

### VPN 10 campus peering iteration pattern

Flatten the three-level nesting (`service_vpns` → `campus_interface.vrfs` →
`[cedge_a, cedge_b]`) into a single `for_each` map before creating resources.

**Critical: `port` lives at `campus_interface` level, not inside `vrf`.** The
`vrf` object has exactly four attributes: `name`, `cedge_a`, `cedge_b`,
`redistribute_omp`. Accessing `each.value.vrf.port` will always fail. Instead,
carry `port` as an explicit top-level field in every flat map entry:

```hcl
locals {
  campus_peers = {
    for item in flatten([
      for vpn in [for v in var.site_cfg.service_vpns : v if v.vpn != 0] : [
        for vrf in vpn.campus_interface.vrfs : [
          for cedge_key in ["cedge_a", "cedge_b"] : {
            key       = "${vpn.vpn}-${vrf.name}-${cedge_key}"
            vpn       = vpn.vpn
            port      = vpn.campus_interface.port   # MUST be explicit — not in vrf
            vrf       = vrf
            cedge     = vrf[cedge_key]
            cedge_key = cedge_key
          }
        ]
      ]
    ]) : item.key => item
  }

  bgp_peers  = { for k, v in local.campus_peers : k => v if v.cedge.bgp  != null }
  ospf_peers = { for k, v in local.campus_peers : k => v if v.cedge.ospf != null }
}
```

Then in every resource that needs the interface name:

```hcl
interface_name = "${each.value.port}.${each.value.cedge.vlan}"
```

Never write `each.value.vrf.port` — it does not exist.

For BGP resources: `neighbor_ip`, `route_map_in`, `route_map_out` are read
from `each.value.cedge.bgp.neighbor_ip` etc. They are never flat on `cedge`.

`route_map_in` and `route_map_out` are string references into
`var.site_cfg.route_maps`. Resolve each non-null reference to the
corresponding `sdwan_service_route_policy_feature` resource ID; `~` means
no policy for that peer. Route-maps apply to BGP only — OSPF peers have
no route-map fields.

`redistribute_omp` is **per VRF**, not per cEdge — read from
`each.value.vrf.redistribute_omp` and apply once to the BGP or OSPF feature
for that VRF. Never set `omp` as a redistribute protocol on any
transport-side resource.

### BGP neighbor description length limit

`sdwan_service_routing_bgp_feature` enforces a **maximum of 32 characters** on
`ipv4_neighbors[0].description`. Always clamp generated descriptions with
`substr(..., 0, 32)` — never build them from free-form string interpolation
without a length guard:

```hcl
description = substr("${var.site_name} ${each.key}", 0, 32)
```

### Route-map resources

`var.site_cfg.route_maps` is a map of named policy definitions. Create one
`sdwan_service_route_policy_feature` (plus `sdwan_policy_object_prefix_list`
when `prefix_list` is non-null) per entry that has at least one non-null
field:

```hcl
for_each = {
  for k, v in try(var.site_cfg.route_maps, {}) : k => v
  if anytrue([for attr in values(v) : attr != null])
}
```

Never create empty route-map or prefix-list resources as placeholders.

### Redistribution — confirmed against the installed provider schema

- **OMP→campus** (`vrf.redistribute_omp`): mapped to `ipv4_redistributes`
  with `protocol = "omp"` in `sdwan_service_routing_bgp_feature` (BGP sites)
  or the equivalent redistribute block in `sdwan_service_routing_ospf_feature`
  (OSPF sites). Per VRF, never per cEdge. Not applicable to VPN 0.
- **Campus→OMP** (`omp_advertise_bgp` top-level YAML field): maps to
  `advertise_ipv4_bgp` on `sdwan_system_omp_feature`. Device-wide boolean,
  belongs in `modules/site`, never inside `modules/service` or per-VRF.
  OSPF sites may also need `advertise_ipv4_ospf` on the same resource.
  Do not nest either field under any `service_vpns` or VRF entry.

## TLOC extension (module/tloc-ext) — OPTIONAL, conditionally instantiated

`modules/site` calls `modules/tloc-ext` **only when `var.site_cfg.tloc_ext
!= null`**. Use the same conditional `for_each`/`count` pattern as
`modules/policy-override` — e.g. `count = var.site_cfg.tloc_ext != null ? 1 : 0`
or a filtered `for_each`. A site with `tloc_ext: ~` (the DC hub) must produce
ZERO TLOC-EXT resources — never a shutdown or administratively-down
placeholder sub-interface. "No TLOC-EXT" is expressed as absent config, not
disabled config.

When instantiated, model TLOC extension as **two TLOC-EXT parcels** inside
the shared transport feature profile (the one `modules/site` creates and
passes to both `modules/transport` and `modules/tloc-ext`), one per
direction — both configured identically on both cEdges at the site:

- Parcel 1 (`sub_if_extend`): extends own `private1` to the peer via VLAN from
  `var.site_cfg.tloc_ext.sub_if_extend.vlan`
- Parcel 2 (`sub_if_receive`): receives peer's `private1`, advertised as `private2`,
  via VLAN from `var.site_cfg.tloc_ext.sub_if_receive.vlan`

The physical port comes from `var.site_cfg.tloc_ext.port`. Never collapse into a
single sub-interface — two VLANs, two parcels, bidirectional.

Do not gate the WAN MPLS interface itself (`transports.private1`) on `tloc_ext` —
the DC hub still has its own `private1` MPLS via a normal WAN interface (it
reaches MPLS through an upstream fusion router). Only the TLOC-EXT parcels
are conditional; the MPLS transport interface is built whenever
`transports.private1` is present, regardless of `tloc_ext`.

## CLI add-on parcel (modules/cli-addon)

Used when a site needs IOS-XE configuration that has no native UX2 parcel —
currently the DC hub. Creates one `sdwan_cli_feature_profile` containing
**two** `sdwan_cli_config_feature` resources:

- `port_channel` — LAG physical members + port-channel sub-interfaces (OSPF, PIM per VRF)
- `supplemental` — VLAN SVI PIM, BFD template, BGP fall-over bfd, BUF-FILTER ACL, PnP startup VLAN

**Conditional instantiation**: `modules/site` calls `modules/cli-addon` only
when `var.site_cfg.cli_addon != null`. Branch sites with `cli_addon: ~`
produce zero CLI add-on resources — same filtered-`for_each` pattern as
`policy_override` and `tloc_ext`.

### Two-stage CLI substitution

- `${...}` — Terraform `templatestring()` resolves these before storing the
  string in vManage. Site-wide values from `var.cli_addon` and `var.site_cfg`.
  Same for both cEdges at a site.
- `{{variable_name}}` — vManage device variables, resolved per device at
  push time. Different for cEdge-A vs cEdge-B. Supplied via the
  `device_variables` map on the attach resource.

### Device variable mapping

| Variable | cEdge-A source | cEdge-B source |
|---|---|---|
| `{{cli_vlan_corp}}` | `vrfs[CORP].cedge_a.vlan` | `vrfs[CORP].cedge_b.vlan` |
| `{{cli_ip_corp}}` | `vrfs[CORP].cedge_a.ip` | `vrfs[CORP].cedge_b.ip` |
| `{{cli_mask_corp}}` | `vrfs[CORP].cedge_a.mask` | `vrfs[CORP].cedge_b.mask` |
| `{{cli_vlan_infra}}` | `vrfs[INFRA].cedge_a.vlan` | `vrfs[INFRA].cedge_b.vlan` |
| `{{cli_ip_infra}}` | `vrfs[INFRA].cedge_a.ip` | `vrfs[INFRA].cedge_b.ip` |
| `{{cli_mask_infra}}` | `vrfs[INFRA].cedge_a.mask` | `vrfs[INFRA].cedge_b.mask` |
| `{{cli_pim_dr_priority}}` | `cli_addon.pim.dr_priority_a` | `cli_addon.pim.dr_priority_b` |
| `{{cli_ospf_md5_secret}}` | `var.ospf_md5_secret` (sensitive) | same value |
| `{{cli_bgp_neighbor_corp}}` | `vrfs[CORP].cedge_a.bgp.neighbor_ip` | `vrfs[CORP].cedge_b.bgp.neighbor_ip` |
| `{{cli_bgp_neighbor_infra}}` | `vrfs[INFRA].cedge_a.bgp.neighbor_ip` | `vrfs[INFRA].cedge_b.bgp.neighbor_ip` |

SVI interface names are derived inline using existing variables — no
separate device variable needed: `Vlan{{cli_vlan_corp}}`, `Vlan{{cli_vlan_infra}}`.

`var.ospf_md5_secret` must be declared `sensitive = true` and passed as a
vManage device variable (`{{cli_ospf_md5_secret}}`) — never embedded by
Terraform into the CLI string to avoid storing plaintext in vManage.

### Dependency rule

Any `sdwan_service_lan_vpn_feature` or `sdwan_service_routing_bgp_feature`
resource whose `interface_name` references `Port-channel<id>` MUST declare:

```hcl
depends_on = [module.cli_addon]
```

### BGP fall-over bfd — critical constraint

The `supplemental` parcel contains `router bgp ${var.cli_addon.bgp.as_number}`
with `fall-over bfd` on each neighbor. IOS-XE merges this into the existing
BGP session created by `sdwan_service_routing_bgp_feature` — it does NOT
replace it. The `as_number` in `cli_addon.bgp.as_number` MUST match the AS
number used by the native BGP parcel (from `globals.yaml.sdwan_as`), in the
exact notation IOS-XE displays it. A mismatch creates a second router bgp
process and the `fall-over bfd` silently applies to the wrong session.

### Wiring device variables into the attach resource

vManage scans `{{variable_name}}` in the CLI string and registers them as
required device variables for the config group. They are supplied in the
**same** `variables` map on `sdwan_attach_feature_device_template` as all
other site variables (`pseudo_commit_timer`, system IPs, etc.) — there is no
separate attach resource for CLI variables.

The key name in the `variables` map must exactly match the `{{name}}` in the
CLI string (no braces, case-sensitive). All values are strings — use
`tostring()` on integers (VLANs, DR priorities). cEdge-A and cEdge-B are
separate `devices` entries with different values:

```hcl
devices = [
  {
    id = var.site_cfg.chassis_a
    variables = {
      pseudo_commit_timer         = "300"
      cli_vlan_corp               = tostring(local.corp.cedge_a.vlan)
      cli_ip_corp                 = local.corp.cedge_a.ip
      cli_mask_corp               = local.corp.cedge_a.mask
      cli_vlan_infra              = tostring(local.infra.cedge_a.vlan)
      cli_ip_infra                = local.infra.cedge_a.ip
      cli_mask_infra              = local.infra.cedge_a.mask
      cli_pim_dr_priority         = tostring(var.site_cfg.cli_addon.pim.dr_priority_a)
      cli_ospf_md5_secret         = var.ospf_md5_secret  # sensitive — redacted in plan/state
      cli_bgp_neighbor_corp       = local.corp.cedge_a.bgp.neighbor_ip
      cli_bgp_neighbor_infra      = local.infra.cedge_a.bgp.neighbor_ip
    }
  },
  {
    id = var.site_cfg.chassis_b
    variables = {
      pseudo_commit_timer         = "300"
      cli_vlan_corp               = tostring(local.corp.cedge_b.vlan)
      cli_ip_corp                 = local.corp.cedge_b.ip
      cli_mask_corp               = local.corp.cedge_b.mask
      cli_vlan_infra              = tostring(local.infra.cedge_b.vlan)
      cli_ip_infra                = local.infra.cedge_b.ip
      cli_mask_infra              = local.infra.cedge_b.mask
      cli_pim_dr_priority         = tostring(var.site_cfg.cli_addon.pim.dr_priority_b)
      cli_ospf_md5_secret         = var.ospf_md5_secret  # same value both cEdges
      cli_bgp_neighbor_corp       = local.corp.cedge_b.bgp.neighbor_ip
      cli_bgp_neighbor_infra      = local.infra.cedge_b.bgp.neighbor_ip
    }
  }
]
```

`var.ospf_md5_secret` must be declared `sensitive = true` in `variables.tf`.
Terraform redacts it in plan output and state. It must never be interpolated
into the `cli` string by `templatestring()` — only passed as a device variable.

### Reference files

Full CLI templates and device variable tables are in:
- `dc-hub_cli_addon_portchannel.txt` — port_channel parcel detail
- `dc-hub_cli_addon_supplemental.txt` — supplemental parcel detail

## Sensitive variables

Any variable holding a credential, PSK, or secret must declare `sensitive = true`.
Never output sensitive values from a module.

## for_each over transport interfaces (data-driven)

`modules/transport` does `for_each` directly over `var.site_cfg.transports`,
which is a map already keyed by color (`custom1`, `custom2`, `private1`). One
WAN interface parcel is rendered per map entry — no hardcoded isp_a/isp_b/mpls
slots, no per-color conditional logic. A site that omits a color simply
produces no parcel for it; never emit a shut/disabled placeholder for an
absent transport.

The color key flows straight through to the resource's `for_each` key, so it
becomes the Terraform state address for that parcel. This is intentional
(stable keys across plans) but means keys are immutable on deployed sites —
a rename is destroy+create. Do not transform or re-key the map inside the
module; use the YAML's color keys verbatim.

Per entry: read `interface`, then branch on the routing method present:

- `dhcp: true` → DHCP WAN interface. No IP address or routing config.
- `ospf` block present → Static IP on the interface (`ip`/`mask`) plus create
  one `sdwan_transport_routing_ospf_feature` per transport feature profile.
  `private1` always uses this path in this design. The OSPF parcel is created
  once per profile (not once per transport entry) — use a `for_each` over
  entries filtered to those with an `ospf` block, or a single conditional
  resource using `any()` over the map.
- neither → Static routing with `ip`/`mask`/`gateway`.

Never assume a uniform method — `custom1`/`custom2` are DHCP; `private1` is
OSPF. They coexist in the same `transports` map.
