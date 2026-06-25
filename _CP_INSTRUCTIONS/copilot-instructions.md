# SD-WAN NaC – Cisco Catalyst SD-WAN Terraform project

## What this repository is

Infrastructure-as-code project managing a Cisco Catalyst SD-WAN fabric using
Terraform. Target platform: vManage 20.13 / IOS-XE 17.13+. All configuration
uses the UX2 paradigm (config groups and parcels). No UX1 feature templates
exist or should be created.

This project enforces **hard state isolation per region** so a change to one
region (e.g. Paris) can never touch another region's resources (e.g. NYC).
See `regions.instructions.md` for the full mechanism.

## Provider

Use `CiscoDevNet/sdwan` exclusively (registry.terraform.io/CiscoDevNet/sdwan).
Never mix with `netascode/sdwan`. Credentials come only from each region's
own `terraform.tfvars` (gitignored) or environment variables
`SDWAN_USERNAME`, `SDWAN_PASSWORD`, `SDWAN_URL`, `SDWAN_INSECURE` (TLS
bypass, defaults to `true`), `SDWAN_RETRIES` (defaults to 3). Never
hardcode credentials in `.tf` files. There is no separate port argument —
include the port directly in `SDWAN_URL`, e.g. `https://10.1.1.1:8443`.

## Repository layout

```
sdwan-nac/
├── modules/
│   ├── site/           # Composes all feature profiles for one site
│   ├── config-group/   # sdwan_configuration_group
│   ├── policy-group/   # Regional policy — instantiated in policy/ stack
│   ├── policy-override/# Optional per-branch additive parcels
│   ├── system-profile/ # AAA/TACACS, NTP, Banner, SNMP, Logging parcels;
│   │                     merges common/*.yaml with site system: overrides
│   ├── transport/      # WAN interface parcels (custom1/2, private1)
│   ├── service/        # LAN VPN parcels, BGP/OSPF, campus peering
│   ├── tloc-ext/       # TLOC extension sub-interfaces
│   └── cli-addon/      # CLI add-on; instantiated when cli_addon != null
├── common/             # Org-wide system profile parameters
│   ├── aaa.yaml        # TACACS servers, auth order
│   ├── ntp.yaml        # NTP servers, timezone
│   ├── banner.yaml     # MOTD and login banner
│   ├── snmp.yaml       # SNMP communities, trap destinations
│   └── logging.yaml    # Syslog servers, log levels
├── globals.yaml        # Org-wide facts + dc_hub read-only reference
├── regions/
│   ├── dc-hub/         # ISOLATED STACK — single combined stack (policy + site)
│   │   ├── sites/dc-hub.yaml
│   │   ├── policy.yaml
│   │   └── main.tf / variables.tf / outputs.tf / tfvars / lock file
│   ├── na/             # Region folder — contains sub-stacks
│   │   ├── policy/     # ISOLATED STACK — regional policy, outputs policy_id
│   │   ├── nyc/        # ISOLATED STACK — NYC site only
│   │   ├── chicago/    # ISOLATED STACK — Chicago site only
│   │   ├── sites/      # YAML files only (nyc.yaml, chicago.yaml)
│   │   └── policy.yaml
│   └── emea/           # Same sub-stack pattern as na/
│       ├── policy/
│       ├── paris/
│       ├── london/
│       ├── sites/
│       └── policy.yaml
└── .gitignore
```

State isolation at two levels: across regions (na/ vs emea/ never share state)
and within a region (nyc/ and chicago/ each have their own `terraform.tfstate`).
The policy/ sub-stack outputs `policy_id`; site stacks read it via
`terraform_remote_state`. Apply policy/ first in a new region.

## Fabric topology

- Every site: 2 × cEdge (IOS-XE), **fully independent** — no HA pair, no
  Redundancy Groups (RG), both active simultaneously
- **Transports are data-driven** — `transports` is a MAP keyed by vManage
  TLOC color (`custom1`, `custom2`, `private1`). Each site declares only the
  circuits it has; the transport module renders one WAN interface parcel per
  map entry via `for_each`. Branch: all three. Internet-only: just
  `custom1`/`custom2`. DC: `custom1`/`custom2`/`private1`. Absent transport =
  absent config, never a shut placeholder port. Color key is the immutable
  state address — never rename on a deployed site.
- **TLOC extension is OPTIONAL and branch-only**. When a site has a non-null
  `tloc_ext` block: one shared physical port per cEdge, 2 sub-interfaces on
  each box (both VLANs present on both routers):
  - Sub-if A (`GigabitEthernet5.101`, VLAN 101): extends own `private1` to
    peer → peer advertises as `private2`
  - Sub-if B (`GigabitEthernet5.102`, VLAN 102): receives peer's `private1`
    → advertised locally as `private2`
  - Such a branch cEdge advertises **4 TLOCs**: `custom1`, `custom2`,
    `private1` (own MPLS), `private2` (peer MPLS via TLOC-EXT)
- **DC hub has NO TLOC-EXT** (`tloc_ext: ~`). An intermediate underlay
  router fuses all MPLS CPEs upstream, so both DC cEdges reach MPLS directly
  over their own WAN interface — no peer MPLS to extend. Each DC cEdge
  advertises **3 TLOCs**: `custom1`, `custom2`, `private1`. No `private2` at
  the DC. The DC keeps its normal `transports.private1` block; only the
  separate `tloc_ext` block is dropped. Never add a TLOC-EXT block back to
  the DC — its absence is intentional.
- `modules/site` instantiates `modules/tloc-ext` only when
  `site_cfg.tloc_ext != null` (same filtered-`for_each` pattern as
  `policy_override`). A null `tloc_ext` produces zero TLOC-EXT resources —
  never a disabled/shutdown placeholder port.
- DC hub (`regions/dc-hub/sites/dc-hub.yaml`) receives hub topology policy
  from `regions/dc-hub/policy.yaml`
- **DC hub campus service side uses a port-channel** — no native UX2 parcel
  exists for LAG/LACP; handled via a CLI add-on feature profile
  (`sdwan_cli_feature_profile` + `sdwan_cli_config_feature`). The site YAML
  carries a `cli_addon.port_channel` block; `campus_interface.port` in VPN 10
  references the derived `Port-channel<id>`. Service resources that reference
  the port-channel must `depends_on` the CLI add-on module. Never use
  `sdwan_cli_template_feature_template` or `sdwan_cli_device_template` — those
  are UX1. Branch sites set `cli_addon: ~` and produce zero CLI add-on resources.
- Branch spokes receive spoke policy from their own region's `policy.yaml`

## Campus peering — SD-WAN to campus fabric

Each site connects to one campus **L3 switch**. Each cEdge (A and B) has its
own dedicated trunk uplink to that switch. **VPN 0 has no campus peering** —
it is transport underlay only. All campus peering sessions are service-side
(VPN 10).

On the service side, **two VRFs are terminated on the SD-WAN edge**: CORP and
INFRA. Each VRF is peered via a dedicated VLAN/SVI on the campus switch.
Because cEdge-A and cEdge-B connect via separate switch ports, they use
**different VLANs** for the same VRF. Per site: 4 peering sessions total
(2 cEdges × 2 VRFs).

The campus peering protocol is **BGP or OSPF** — chosen per cEdge via a `bgp`
or `ospf` sub-block inside each `cedge_a`/`cedge_b` entry. Exactly one
sub-block is non-null; the other is `~`. The module branches on which is
non-null to create either `sdwan_service_routing_bgp_feature` or
`sdwan_service_routing_ospf_feature`.

VPN 10's campus trunk carries two VLANs (one per VRF). The sub-interface on
the cEdge is `<port>.<vlan>` (e.g. `GigabitEthernet6.3110`). cEdge-A and
cEdge-B never share a VLAN for the same VRF.

Redistribution is **not symmetric**: OMP→campus (`redistribute_omp: true` per
VRF) is configured in the BGP or OSPF feature resource for VPN 10 only.
Campus→OMP is a single device-wide boolean (`advertise_ipv4_bgp` on
`sdwan_system_omp_feature`), set via the top-level `omp_advertise_bgp` YAML
field — NOT per-VPN, NOT per-VRF, never nested under `service_vpns`. OSPF
sites may require `advertise_ipv4_ospf` on the same resource.

Route-maps apply to **BGP only** — defined as a named library in `route_maps:`
at the site YAML top level. Each `bgp` sub-block references a policy by name
via `route_map_in`/`route_map_out`, or `~` for none. OSPF sites do not use
route-maps at the campus peering level.

## Regional shared policy

Each region has exactly ONE shared policy baseline (QoS classes,
hub-and-spoke topology, app-route SLA classes) defined in that region's
`policy.yaml` and instantiated once via `modules/policy-group`. Every site
in the region attaches its config group to this single policy.

A branch may optionally diverge with a `policy_override` block in its site
YAML — additive only, never a replacement of the regional baseline. Create
`modules/policy-override` resources only for sites where `policy_override`
is non-null.

The DC hub's identity (site-id, system IPs) is needed by every region's
topology policy but must never be a managed resource outside
`regions/dc-hub/`. It lives as read-only reference data in `globals.yaml`
under `dc_hub:` and is read via `yamldecode`, never created or modified by
a region's own Terraform.

## Site YAML schema

Two variants cover all branch topologies. The DC hub uses its own separate YAML
variant. The only fields that differ between branch variants are `transports` and
`tloc_ext`; everything else is structurally identical.

### Variant A — full branch (dual internet + MPLS + TLOC-EXT)

4 TLOCs per cEdge: `custom1`, `custom2`, `private1` (own MPLS), `private2`
(peer MPLS via TLOC-EXT).

```yaml
site_id: 200                        # Unique GLOBALLY, not just per region
system_ip_a: 10.0.1.1
system_ip_b: 10.0.1.2
hostname_a: nyc-cedge-01
hostname_b: nyc-cedge-02
chassis_a: "CSR1000V-..."
chassis_b: "CSR1000V-..."

transports:                         # MAP keyed by TLOC color — for_each in module.
                                    # Color key is immutable state address; never
                                    # rename on a deployed site (rename = TLOC flap).
  custom1:                          # ISP-A (DHCP)
    interface: GigabitEthernet2
    dhcp: true
  custom2:                          # ISP-B (DHCP)
    interface: GigabitEthernet3
    dhcp: true
  private1:                         # Own MPLS (OSPF underlay toward PE)
    interface: GigabitEthernet4
    ip: 192.168.1.1
    mask: 255.255.255.252
    ospf:
      area: 0                       # OSPF area (integer). No gateway — OSPF replaces
                                     # static routing for private colors.
  # No private2 entry — derived via tloc_ext, not a local circuit

tloc_ext:
  port: GigabitEthernet5
  sub_if_extend:                    # Extends own private1 to peer → peer sees as private2
    sub_interface: GigabitEthernet5.101
    vlan: 101
  sub_if_receive:                   # Receives peer's private1 → local private2
    sub_interface: GigabitEthernet5.102
    vlan: 102

route_maps: {}                      # Named library. Add entries when policies are needed;
                                     # peers reference by name. ~ = no policy applied.

service_vpns:
  - vpn: 0
    name: TRANSPORT                 # Transport underlay only. No campus interface,
                                     # no BGP. Never routed to modules/service.

  - vpn: 10
    name: LAN
    campus_interface:
      port: GigabitEthernet6        # Trunk port. Sub-if = <port>.<vlan>.
      vrfs:
        - name: CORP
          cedge_a:
            vlan: 3110
            ip: 10.10.1.1
            mask: 255.255.255.252
            bgp:                    # non-null = BGP campus peering; ~ for OSPF sites
              neighbor_ip: 10.10.1.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~                 # non-null = OSPF campus peering; ~ for BGP sites
          cedge_b:
            vlan: 3111              # Different VLAN — same VRF, different SVI
            ip: 10.10.2.1
            mask: 255.255.255.252
            bgp:
              neighbor_ip: 10.10.2.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~
          redistribute_omp: true    # OMP → campus protocol, per-VRF, not per-cEdge
        - name: INFRA
          cedge_a:
            vlan: 3120
            ip: 10.20.1.1
            mask: 255.255.255.252
            bgp:
              neighbor_ip: 10.20.1.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~
          cedge_b:
            vlan: 3121
            ip: 10.20.2.1
            mask: 255.255.255.252
            bgp:
              neighbor_ip: 10.20.2.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~
          redistribute_omp: true

omp_advertise_bgp: true             # Device-wide (NOT per-VRF). Maps to
                                     # sdwan_system_omp_feature.advertise_ipv4_bgp.

policy_override: ~                  # Optional additive per-branch policy
```

### Variant B — internet-only branch (dual internet, no MPLS)

2 TLOCs per cEdge: `custom1`, `custom2` only. `tloc_ext: ~` → zero TLOC-EXT
resources — never a shutdown placeholder port.

```yaml
site_id: 201
system_ip_a: 10.0.2.1
system_ip_b: 10.0.2.2
hostname_a: chi-cedge-01
hostname_b: chi-cedge-02
chassis_a: "CSR1000V-..."
chassis_b: "CSR1000V-..."

transports:
  custom1:
    interface: GigabitEthernet2
    dhcp: true
  custom2:
    interface: GigabitEthernet3
    dhcp: true
  # No private1 — internet-only site

tloc_ext: ~                         # No MPLS → no TLOC-EXT. 2 TLOCs: custom1, custom2.

route_maps: {}

service_vpns:
  - vpn: 0
    name: TRANSPORT

  - vpn: 10
    name: LAN
    campus_interface:
      port: GigabitEthernet6
      vrfs:
        - name: CORP
          cedge_a:
            vlan: 3110
            ip: 10.10.1.1
            mask: 255.255.255.252
            bgp:
              neighbor_ip: 10.10.1.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~
          cedge_b:
            vlan: 3111
            ip: 10.10.2.1
            mask: 255.255.255.252
            bgp:
              neighbor_ip: 10.10.2.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~
          redistribute_omp: true
        - name: INFRA
          cedge_a:
            vlan: 3120
            ip: 10.20.1.1
            mask: 255.255.255.252
            bgp:
              neighbor_ip: 10.20.1.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~
          cedge_b:
            vlan: 3121
            ip: 10.20.2.1
            mask: 255.255.255.252
            bgp:
              neighbor_ip: 10.20.2.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~
          redistribute_omp: true

omp_advertise_bgp: true

policy_override: ~
```

## Region `policy.yaml` schema

```yaml
region: na
qos:
  classes:
    - name: VOICE
      bandwidth_percent: 30
      dscp: 46                      # decimal only — 46 = EF
    - name: BUSINESS_CRITICAL
      bandwidth_percent: 40
      dscp: 26                      # decimal only — 26 = AF31
    - name: DEFAULT
      bandwidth_percent: 30
      dscp: 0                       # decimal only — 0 = default/BE
topology:
  type: hub_and_spoke               # hub identity from globals.yaml dc_hub
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

**DSCP must be a decimal integer, never a PHB keyword.** The provider
rejects `ef`/`af31`/`cs5`/`default`. Decimal equivalents: EF=46, AF11=10,
AF21=18, AF31=26, AF41=34, CS5=40, CS6=48, default/BE=0. Applies to regional
QoS classes and any `policy_override.qos` block. Convert keywords to decimal;
never pass a keyword through.

## globals.yaml schema

```yaml
org_name: acme-corp
vmanage_url: https://vmanage.acme.corp
sdwan_as: 65000
campus_as: 65100
dc_hub:
  site_id: 100
  system_ip_a: 10.0.0.1
  system_ip_b: 10.0.0.2
```

## Per-region main.tf pattern

```hcl
locals {
  globals = yamldecode(file("${path.module}/../../globals.yaml"))
  policy  = yamldecode(file("${path.module}/policy.yaml"))
  sites = {
    for f in fileset(path.module, "sites/*.yaml") :
    trimsuffix(basename(f), ".yaml") => yamldecode(file(f))
  }
}

module "regional_policy" {
  source      = "../../modules/policy-group"
  region_name = "na"
  policy_cfg  = local.policy
  dc_hub      = local.globals.dc_hub
}

module "site" {
  for_each = local.sites
  source   = "../../modules/site"
  site_name          = each.key
  site_cfg           = each.value
  globals            = local.globals
  regional_policy_id = module.regional_policy.policy_id
}

module "policy_override" {
  for_each = { for k, v in local.sites : k => v if v.policy_override != null }
  source   = "../../modules/policy-override"
  site_name       = each.key
  override_cfg    = each.value.policy_override
  config_group_id = module.site[each.key].config_group_id
}
```

## Commands to know

```bash
cd regions/na                       # ALWAYS start here — never run terraform
                                     # from the repo root
terraform init -upgrade             # Per-region — separate lock file each
terraform fmt -recursive
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
terraform plan -target='module.site["nyc"]'      # Single-site within region
terraform state list | grep nyc
terraform state show 'module.site["nyc"].module.config_group.sdwan_configuration_group.this'
```

## Hard rules

- Never run `terraform apply` without showing the plan and waiting for approval.
- Every device attach MUST include `pseudo_commit_timer = 300` in its
  variables/device_variables map — the attach fails without it. It's a fixed
  constant, not a per-site YAML field; bake it into the attach resource or a
  defaulted module variable so it can never be forgotten on a new site.
- DSCP values are always decimal integers, never PHB keywords (no `ef`,
  `af31`, `default` — use 46, 26, 0).
- Never create a root-level stack that spans multiple regions — every
  Terraform root module lives inside exactly one `regions/<name>/` folder.
- Never use `sdwan_feature_template`, `sdwan_cli_template_feature_template`,
  or `sdwan_cli_device_template` — all three are UX1. The UX2 CLI add-on
  uses `sdwan_cli_feature_profile` + `sdwan_cli_config_feature` only.
- Never use `terraform taint` or `terraform state rm` without explicit
  user approval.
- Never commit `terraform.tfvars`, `*.tfstate`, or `.terraform/` from any
  region directory.
- Never let `regions/dc-hub/` be modified as a side effect of a regional
  change — manage it only from inside its own directory.
- When editing a shared module (`modules/*`), explicitly tell the user that
  the diff will appear in every region using it on their next plan — that
  is the one legitimate case where a single change affects multiple
  regions' plans (each still applies independently).
- State backend is local, one per region. Do not add a remote backend
  spanning multiple regions unless explicitly asked.
- Provider docs: https://registry.terraform.io/providers/CiscoDevNet/sdwan/latest/docs
