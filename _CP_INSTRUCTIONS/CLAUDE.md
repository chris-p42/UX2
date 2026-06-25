# SD-WAN NaC – Terraform project context

## What this repository is

Infrastructure-as-code project managing a Cisco Catalyst SD-WAN fabric using
Terraform. Target platform: vManage 20.13 / IOS-XE 17.13+. All configuration
uses the UX2 paradigm (config groups and parcels). No UX1 feature templates
exist or should be created.

This project enforces **hard state isolation per region** so that a change to
one region (e.g. Paris) can never touch another region's resources (e.g. NYC),
even accidentally. See "Multi-region state isolation" below — this is a load-
bearing architectural decision, not a convenience.

## Terraform provider

Use `CiscoDevNet/sdwan` exclusively (registry.terraform.io/CiscoDevNet/sdwan).
Never mix with `netascode/sdwan`. Credentials come only from each region's own
`terraform.tfvars` (gitignored) or environment variables `SDWAN_USERNAME`,
`SDWAN_PASSWORD`, `SDWAN_URL`, `SDWAN_INSECURE` (TLS verification bypass,
provider defaults this to `true` already), `SDWAN_RETRIES` (REST call
retry count, defaults to 3). Never hardcode credentials in `.tf` files.
There is no separate port argument — include the port directly in
`SDWAN_URL`, e.g. `https://vmanage.acme.corp:8443`.

## Repository layout

```
sdwan-nac/
├── modules/                          # Shared, region-agnostic modules
│   ├── site/                         # Composes config-group + all feature profiles
│   │                                   for one site; accepts regional_policy_id
│   ├── config-group/                 # sdwan_configuration_group + parcels
│   ├── policy-group/                 # REGIONAL shared policy: topology
│   │                                   (hub-and-spoke), QoS, app-route —
│   │                                   instantiated ONCE per region in policy/ stack
│   ├── policy-override/              # Optional per-branch additive parcels
│   ├── system-profile/               # System parcels: AAA/TACACS, NTP, Banner,
│   │                                   SNMP, Logging — merges common/*.yaml with
│   │                                   site YAML system: overrides
│   ├── transport/                    # WAN interface parcels (custom1/2, private1)
│   ├── service/                      # LAN VPN parcels, BGP/OSPF, campus peering
│   ├── tloc-ext/                     # TLOC extension sub-interfaces
│   └── cli-addon/                    # CLI add-on parcel for features without a
│                                       native UX2 parcel (e.g. DC hub port-channel)
│
├── common/                           # Org-wide system profile parameters
│   ├── aaa.yaml                      # TACACS servers, auth order
│   ├── ntp.yaml                      # NTP servers, timezone, auth keys
│   ├── banner.yaml                   # MOTD and login banner text
│   ├── snmp.yaml                     # SNMP communities, trap destinations
│   └── logging.yaml                  # Syslog servers, log levels
│
├── globals.yaml                      # Org-wide facts: org-name, vManage URL,
│                                        AS numbers, dc_hub identity (read-only)
│
├── regions/
│   ├── dc-hub/                       # ISOLATED STACK — DC hub only.
│   │   │                               Single site; policy and site share one stack
│   │   │                               (no per-site split needed for one site).
│   │   ├── sites/dc-hub.yaml
│   │   ├── policy.yaml
│   │   ├── main.tf / variables.tf / outputs.tf
│   │   ├── terraform.tfvars          # gitignored
│   │   └── .terraform.lock.hcl
│   │
│   ├── na/                           # NA region folder — contains sub-stacks
│   │   ├── policy/                   # ISOLATED STACK — regional policy only
│   │   │   ├── main.tf               # instantiates modules/policy-group; outputs policy_id
│   │   │   ├── variables.tf
│   │   │   ├── outputs.tf            # output: policy_id
│   │   │   ├── terraform.tfvars      # gitignored
│   │   │   └── .terraform.lock.hcl
│   │   ├── nyc/                      # ISOLATED STACK — NYC site only
│   │   │   ├── main.tf               # reads ../sites/nyc.yaml + policy_id from ../policy/
│   │   │   ├── variables.tf
│   │   │   ├── outputs.tf
│   │   │   ├── terraform.tfvars      # gitignored
│   │   │   └── .terraform.lock.hcl
│   │   ├── chicago/                  # ISOLATED STACK — Chicago site only
│   │   │   └── (same structure as nyc/)
│   │   ├── sites/                    # YAML files — not Terraform roots
│   │   │   ├── nyc.yaml
│   │   │   └── chicago.yaml
│   │   └── policy.yaml               # NA-wide QoS + topology + app-route baseline
│   │
│   └── emea/                         # EMEA region — same sub-stack pattern as na/
│       ├── policy/
│       ├── paris/
│       ├── london/
│       ├── sites/
│       │   ├── paris.yaml
│       │   └── london.yaml
│       └── policy.yaml
│
└── .gitignore
```

**State isolation operates at two levels:**
- **Across regions**: `regions/na/` and `regions/emea/` are fully separate — no shared state, lock file, or apply invocation.
- **Within a region**: each branch site has its own sub-stack (`regions/na/nyc/`, `regions/na/chicago/`) with its own `terraform.tfstate`. A `terraform apply` in `nyc/` can never touch `chicago/` resources. The regional policy is a third isolated sub-stack (`regions/na/policy/`) whose output (`policy_id`) is read by each site stack via `terraform_remote_state`.

## Multi-region state isolation

### Why this exists

The explicit requirement driving this architecture: a change pushed to one
region (e.g. Paris, outside office hours) must never be able to impact another
region (e.g. NYC), even through human error, a bad `-target`, or a buggy
shared module. The only mechanism that gives a *hard* guarantee of this is
state separation — if NYC's resources are not in the same state file as
Paris's, there is no Terraform command that can touch both at once.

### How it works

Each Terraform stack is a subdirectory with its own `terraform.tfstate`,
`.terraform/` working directory, and `.terraform.lock.hcl`. Within a region,
there are **three kinds of stacks**, each isolated:

1. **`regions/<name>/policy/`** — regional policy only. Run first (or whenever
   `policy.yaml` changes). Outputs `policy_id`. A `terraform apply` here
   cannot touch any branch device.
2. **`regions/<name>/<site>/`** — one stack per branch site. Reads its site
   YAML from `../sites/<site>.yaml` and the policy ID from `../policy/` via
   `terraform_remote_state`. A `terraform apply` here can only touch that
   one site's resources.
3. **`regions/dc-hub/`** — single combined stack (policy + site in one, since
   there is only one hub site). Most critical; touched least often.

To work on a site, `cd regions/<name>/<site>/`. Every `terraform` command
operates only on that directory's state — it cannot reach another site's
resources even with a bad `-target`.

### What is and isn't isolated

- **Across regions**: fully isolated. NA and EMEA never share a state file,
  a lock file, or a `terraform apply` invocation.
- **Within a region**: each branch site has its own state. `terraform apply`
  in `nyc/` cannot touch `chicago/` or any other site.
- **The regional policy** is its own isolated stack (`policy/`). A change to
  `policy.yaml` or `modules/policy-group` only affects the policy stack's
  plan — branch sites read the policy ID as data, they do not re-apply it.
  If a site needs something different from the regional baseline, use
  `policy_override` rather than forking the regional policy.

### Hub reference without shared state

Regional topology policies (hub-and-spoke) need to know the DC hub's
identity (site-id, system IPs) to build correct hub-spoke definitions —
but regions must never manage or have write access to the hub's actual
devices. This is solved by keeping the hub's identity as **read-only
reference data** in the repo-root `globals.yaml`:

```yaml
dc_hub:
  site_id: 100
  system_ip_a: 10.0.0.1
  system_ip_b: 10.0.0.2
```

Every region's `main.tf` reads this via `yamldecode(file("${path.module}/../../globals.yaml"))`
and passes `local.globals.dc_hub` into its `modules/policy-group` call. Only
`regions/dc-hub/` actually creates and manages the hub's devices and config
group — every other region treats this block as informational lookup data,
never as a managed resource.

## Site topology

- **Every site**: 2 × cEdge (IOS-XE), **fully independent** — no HA pair, no
  Redundancy Groups (RG), both active simultaneously
- **Transports are data-driven, not fixed** — `transports` is a map keyed by
  vManage TLOC color (`custom1`, `custom2`, `private1`). Each site declares
  only the circuits it physically has; the transport module renders one WAN
  interface parcel per map entry via `for_each`. A typical branch declares
  all three; an internet-only site declares just `custom1`/`custom2`; the DC
  declares `custom1`/`custom2`/`private1`. **Absent transport = absent config**,
  never a shut/disabled placeholder port (see "Architectural decision:
  data-driven transports" below for why). The color key is the immutable
  state address — never rename a key on a deployed site.
- **TLOC extension is OPTIONAL and branch-specific**: at a branch, each cEdge
  has only its own single MPLS circuit, so the two cEdges share their
  `private1` TLOCs peer-to-peer via TLOC-EXT — giving each cEdge **4 TLOCs**
  (`custom1`, `custom2`, `private1` own, `private2` peer-via-EXT). See the
  TLOC extension section below for the mechanics. A site that doesn't need
  this sets `tloc_ext: ~` and gets no TLOC-EXT config at all.
- **DC hub** (`regions/dc-hub/sites/dc-hub.yaml`): **no TLOC-EXT**
  (`tloc_ext: ~`). An intermediate underlay router fuses all the MPLS CPEs
  into one upstream, so both DC cEdges reach MPLS directly over their own
  WAN interface — there is no peer MPLS to extend. Each DC cEdge therefore
  advertises **3 TLOCs**: `custom1`, `custom2`, `private1`. There is no
  `private2` at the DC. Do not "add back" a TLOC-EXT block to the DC
  thinking it was omitted by mistake — its absence is intentional and
  correct. The DC keeps its normal `transports.private1` block; only the
  separate `tloc_ext` block is dropped.
- Hub receives hub topology policy from `regions/dc-hub/policy.yaml`;
  branch spokes receive spoke policy from their region's `policy.yaml`.

## TLOC extension (optional, branch-only)

Applies only to sites with a non-null `tloc_ext` block. When present, each
cEdge has **one shared physical port** (e.g. `GigabitEthernet5`) carrying
**two sub-interfaces**, both VLANs configured identically on both routers:

| Sub-interface | VLAN | Direction | Effect |
|---|---|---|---|
| `GigabitEthernet5.101` | 101 | Extend own `private1` → peer | Peer advertises it as `private2` |
| `GigabitEthernet5.102` | 102 | Receive peer's `private1` | Advertised locally as `private2` |

Modelled in `modules/tloc-ext` using two TLOC-EXT parcels inside the shared
transport feature profile. VLAN IDs come from
`site_cfg.tloc_ext.sub_if_extend.vlan` and `site_cfg.tloc_ext.sub_if_receive.vlan`.

**Conditional instantiation**: `modules/site` calls `modules/tloc-ext` only
when `site_cfg.tloc_ext != null`, using the same filtered-`for_each` pattern
proven for `policy_override`. A site with `tloc_ext: ~` (e.g. the DC hub)
gets zero TLOC-EXT resources — never a shutdown/disabled placeholder port.
Expressing "no TLOC-EXT" as absent config (not disabled config) keeps the
running config honest and audit-clean.

## CLI add-on parcel (DC hub port-channel)

The DC hub cEdges connect to the campus switch via a **port-channel** on the
service side. The UX2 provider has no native port-channel interface parcel
(`sdwan_service_lan_vpn_interface_*` does not cover LAG/LACP as of 20.13).
The solution is a **CLI add-on feature profile** — a first-class UX2 construct
(not a UX1 CLI template) that carries raw IOS-XE CLI and attaches to the
config group alongside the native feature profiles.

### Resources used

- `sdwan_cli_feature_profile` — the CLI profile container (added to the config group)
- `sdwan_cli_config_feature` — the parcel inside the profile; holds raw IOS-XE CLI

Do NOT use `sdwan_cli_template_feature_template` or `sdwan_cli_device_template`
— both are UX1 constructs.

### Config group structure at the DC hub

```
sdwan_configuration_group
  ├── sdwan_system_feature_profile
  ├── sdwan_transport_feature_profile
  ├── sdwan_service_feature_profile   ← VPN 10 references Port-channel<id>
  └── sdwan_cli_feature_profile       ← new; contains cli_config_feature
        └── sdwan_cli_config_feature  ← raw IOS-XE: channel-group on members +
                                         interface Port-channel<id> definition
```

### Site YAML — `cli_addon` block

Optional top-level block; set to `~` for branch sites (no port-channel).
When present at the DC hub:

```yaml
cli_addon:                        # ~ for branch sites; non-null triggers cli-addon module
  port_channel:
    id: 10                        # Logical interface becomes Port-channel<id>
    mode: active                  # LACP mode: active | passive | on
    members:
      - TenGigabitEthernet0/0/0
      - TenGigabitEthernet0/0/1
  campus_ospf:
    process_id: 10                # ip ospf <id> area 0
    cost: 100                     # ip ospf cost — same both cEdges
    md5_key_id: 7                 # ip ospf message-digest-key <id> md5 ...
    # MD5 secret: NOT in YAML — sensitive Terraform variable
  pim:
    dr_priority_a: 10             # cEdge-A wins DR election
    dr_priority_b: 1              # cEdge-B is backup DR
    rp_address: 10.99.9.254       # ip pim vrf 10 rp-address
  private_interface:
    speed_config: "no negotiation auto"  # IOS lines injected under transports.private1.interface
  bgp:
    as_number: "10.10"            # router bgp AS — MUST match globals.yaml.sdwan_as in the
                                  # notation IOS-XE displays it; mismatch = fall-over bfd
                                  # creates a second BGP process instead of extending the native one
  buf_filter:
    host_a: 10.99.14.3            # BUF-FILTER ACL endpoint (was hardcoded in UX1)
    host_b: 10.22.108.4
  pnp_startup_vlan: 62            # pnp startup-vlan (was hardcoded in UX1)
```

`campus_interface.port` in VPN 10 then references the derived name
(`Port-channel10`), not a physical interface.

Two `sdwan_cli_config_feature` resources are created inside the single
`sdwan_cli_feature_profile`: `port_channel` (LAG + sub-interfaces) and
`supplemental` (SVI PIM, BFD, BGP fall-over, ACL, PnP). See reference
files `dc-hub_cli_addon_portchannel.txt` and
`dc-hub_cli_addon_supplemental.txt` for the full CLI templates and
device variable mapping.

### Dependency rule

Service VPN resources that reference `Port-channel<id>` MUST declare
`depends_on` the `sdwan_cli_config_feature` resource — otherwise vManage
may push the service parcel before the port-channel definition exists on
the device.

### Conditional instantiation

`modules/site` calls `modules/cli-addon` only when
`var.site_cfg.cli_addon != null`, using the same filtered-`for_each` pattern
as `policy_override` and `tloc_ext`. Branch sites with `cli_addon: ~` produce
zero CLI add-on resources.

## Architectural decision: data-driven transports (not shut-port placeholders)

This was a deliberate design choice — recorded here so it isn't relitigated
or accidentally reversed by a future session.

**Decision**: one parameterized, data-driven model. Each site's YAML declares
exactly the transports it has (as a color-keyed map) plus an optional
`tloc_ext` block. Modules render only what's declared. An absent transport or
a null `tloc_ext` produces *no* corresponding config — never an
administratively-shut placeholder interface.

**Rejected alternative A — uniform full config with shut/no-shut toggles**:
keep every device structurally identical and disable unused ports. Rejected
because (1) transport sets are basically fixed once a site deploys, so the
main benefit (fast day-2 turn-up of a pre-staged port) rarely pays off;
(2) shut placeholders add audit noise and a drift risk (a human can
out-of-band `no shut` a port, creating a live TLOC the overlay doesn't
expect); (3) for TLOC-EXT specifically, a shut placeholder actively
misrepresents topology — it implies a peer-MPLS-sharing relationship that
doesn't exist.

**Rejected alternative B — a separate module/config per transport scenario**
(2ISP/0MPLS, 1ISP/1MPLS, …): rejected outright as a combinatorial
maintenance nightmare. NOTE: option C is NOT this. C keeps ONE module and
ONE schema; only the *data* varies per site, never the code path. If a future
change starts forking module code per scenario, that's drift back toward B —
stop and reconsider.

**Consequence to respect**: because the transport module does `for_each` over
the color-keyed map, each color key becomes part of the Terraform state
address (`...transports["private1"]`). Renaming a key on a deployed site is a
destroy+create, which flaps that TLOC. Transport map keys are immutable
identifiers once deployed — treat them like primary keys.

## Campus peering — SD-WAN to campus fabric

### Overview

Each site connects to one campus **L3 switch**. Each cEdge (A and B) has its
own dedicated trunk uplink to that switch — two separate physical connections
on the same interface name (e.g. `GigabitEthernet6`) since they are
independent devices.

On the service side, **two VRFs are terminated on the SD-WAN edge**: CORP
and INFRA. Each VRF is peered via a dedicated VLAN/SVI on the campus switch.
Because cEdge-A and cEdge-B connect via separate switch ports, they use
**different VLANs** for the same VRF — the switch carries each as an
independent SVI within that VRF.

The campus peering protocol is **BGP or OSPF**, configured per cEdge via a
`bgp` or `ospf` sub-block in the site YAML — exactly one is non-null per cEdge
per VRF. Per site: 4 peering sessions total (2 cEdges × 2 VRFs), all
service-side (VPN 10). **VPN 0 has no campus peering** — transport underlay
only. BGP AS numbers (`sdwan_as`, `campus_as` from `globals.yaml`) are only
relevant when `bgp` sub-blocks are non-null.

### VPN 0 — transport underlay, no campus BGP

VPN 0 is the SD-WAN transport underlay. It carries WAN circuit parcels
(`sdwan_transport_wan_vpn_interface_ethernet_feature`) and nothing else. There
is no campus-facing sub-interface on VPN 0, no BGP session toward campus, and
no route exchange between VPN 0 and the campus switch.
`sdwan_transport_routing_bgp_feature` is not used in this design.

### VPN 10 — service side, two-VRF campus trunk

VPN 10 is the single service VPN. Each cEdge's campus trunk port carries two
VLANs, one per VRF. The sub-interface on the cEdge is derived as
`<port>.<vlan>` (e.g. `GigabitEthernet6.3110`). Each VLAN maps to a
dedicated SVI on the campus switch within the respective VRF:

| VRF | cEdge-A VLAN | cEdge-B VLAN |
|-----|--------------|--------------|
| CORP | 3110 (example) | 3111 (example) |
| INFRA | 3120 (example) | 3121 (example) |

The neighbor IP for each BGP session is the campus switch SVI IP for that
VLAN. cEdge-A and cEdge-B never share a VLAN or a neighbor IP for the same
VRF — they always have distinct SVIs.

### Redistribution — confirmed against the actual provider schema

The two directions are **not symmetric** and live on completely different
resources. Verified directly against the installed provider's
`terraform providers schema -json` output:

- **OMP → campus** (`redistribute_omp: true` per VRF in site YAML): configured
  in `sdwan_service_routing_bgp_feature` (BGP sites) or
  `sdwan_service_routing_ospf_feature` (OSPF sites) for VPN 10. Valid on
  service-side only — never applicable to VPN 0.
- **Campus → OMP** (`omp_advertise_bgp` top-level site YAML field): a single
  device-wide boolean, `advertise_ipv4_bgp`, on `sdwan_system_omp_feature` —
  attached to each cEdge's System feature profile. Set once per site, applied
  identically to both cEdges. NOT per-VPN, NOT per-VRF — never nest it under
  any `service_vpns` or VRF entry. OSPF sites may require `advertise_ipv4_ospf`
  on the same resource — confirm against the provider schema when implementing
  OSPF campus peering.

### Route-maps (BGP only)

Route-maps are defined as a **named library** at the top of the site YAML
under `route_maps:`. They apply only to BGP peers — each `bgp` sub-block
within `cedge_a`/`cedge_b` references a policy by name via `route_map_in` /
`route_map_out`, or `~` for none. OSPF sites do not use route-maps at the
campus peering level.

Terraform creates one `sdwan_service_route_policy_feature` resource per named
entry that has at least one non-null field — keyed by the policy name, not by
the peer. The same named policy can be referenced by any number of peers. Any
number of named policies may be defined.

Reserved knobs per entry: `prefix_list`, `set_local_pref`, `set_med`,
`set_community`, `as_path_prepend`. Set unused fields to `~`.

## Regional shared policy

### Concept

Each region has exactly **one** shared policy baseline — QoS classes,
hub-and-spoke topology, and app-route SLA classes — defined in that region's
`policy.yaml` and instantiated once via `modules/policy-group`. Every site in
the region attaches its config group to this single policy. This is what
allows "similar QoS and traffic policy" per region while still letting
individual branches diverge when needed (see policy_override below).

### `regions/<name>/policy.yaml` schema

```yaml
region: na                          # informational, should match folder name

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
  type: hub_and_spoke                # hub identity comes from globals.yaml
                                      # dc_hub block — never duplicated here

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

**DSCP values must be decimal integers only — never PHB keyword strings.**
The provider rejects `ef`, `af31`, `cs5`, `default`, etc. Use the decimal
equivalent: EF = 46, AF11 = 10, AF21 = 18, AF31 = 26, AF41 = 34, CS5 = 40,
CS6 = 48, default/BE = 0. This applies anywhere a DSCP appears (regional QoS
classes here, and any `policy_override.qos` block). If a future session or
YAML author writes a keyword, convert it to decimal — do not pass it through.

### Per-branch policy override (on-demand)

A branch may need something beyond the regional baseline — e.g. a higher
voice bandwidth allocation, or a different preferred SLA class. This is an
**optional, additive** block in that branch's site YAML:

```yaml
policy_override:                    # Optional — omit entirely if not needed
  qos:
    class_name: VOICE
    bandwidth_percent: 45           # Overrides the regional default, this site only
  app_route:
    sla_class: REALTIME
    preferred_color: private1
```

Terraform rule: only instantiate `modules/policy-override` for sites where
`policy_override` is non-null. Never create empty override resources. The
override always layers additively on top of the regional policy — it never
replaces it.

## YAML site schema — branch sites

Two variants cover all branch topologies. The DC hub has its own distinct YAML
schema (separate file, not shown here). The only fields that differ between the
two branch variants are `transports` and `tloc_ext` — everything else
(`route_maps`, `service_vpns`, `omp_advertise_bgp`, `policy_override`) is
structurally identical.

### Variant A — full branch (dual internet + MPLS + TLOC-EXT)

4 TLOCs per cEdge: `custom1`, `custom2`, `private1` (own MPLS), `private2`
(peer MPLS received via TLOC-EXT).

```yaml
site_id: 200                        # Unique GLOBALLY across all regions
system_ip_a: 10.0.1.1
system_ip_b: 10.0.1.2
hostname_a: nyc-cedge-01
hostname_b: nyc-cedge-02
chassis_a: "CSR1000V-..."
chassis_b: "CSR1000V-..."

transports:
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
      area: 0                       # OSPF area (integer). No gateway field — OSPF
                                     # replaces static routing for private colors.
  # No private2 entry — private2 is derived via tloc_ext, not a local circuit

tloc_ext:
  port: GigabitEthernet5
  sub_if_extend:                    # Extends own private1 to peer → peer sees it as private2
    sub_interface: GigabitEthernet5.101
    vlan: 101
  sub_if_receive:                   # Receives peer's private1 → advertised locally as private2
    sub_interface: GigabitEthernet5.102
    vlan: 102

route_maps: {}                      # No named route-map policies at this site.
                                     # Add named entries here when policies are needed;
                                     # each peer references by name via route_map_in/out.

service_vpns:
  - vpn: 0
    name: TRANSPORT                 # Transport underlay only — no campus interface,
                                     # no BGP. Never routed to modules/service.

  - vpn: 10
    name: LAN
    campus_interface:
      port: GigabitEthernet6        # Physical trunk port toward campus L3 switch.
                                     # Sub-interface = <port>.<vlan>.
      vrfs:
        - name: CORP
          cedge_a:
            vlan: 3110              # cEdge-A VLAN — its own SVI on campus switch
            ip: 10.10.1.1
            mask: 255.255.255.252
            bgp:                    # non-null = BGP campus peering; ~ for OSPF sites
              neighbor_ip: 10.10.1.2
              route_map_in: ~       # Name from route_maps above, or ~ for no policy
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
          redistribute_omp: true    # OMP → campus protocol, per-VRF, not per-cEdge.
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
                                     # Applied identically to both cEdges.

policy_override: ~                  # Optional — see "Per-branch policy override" above
```

### Variant B — internet-only branch (dual internet, no MPLS)

2 TLOCs per cEdge: `custom1`, `custom2` only. No MPLS circuit means no TLOC-EXT.
`tloc_ext: ~` produces zero TLOC-EXT resources — never a shutdown placeholder port.

```yaml
site_id: 201                        # Unique GLOBALLY across all regions
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
  # No private1 — internet-only site, no MPLS circuit

tloc_ext: ~                         # No MPLS → no TLOC-EXT.
                                     # 2 TLOCs per cEdge: custom1, custom2.

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

## globals.yaml schema

```yaml
org_name: acme-corp
vmanage_url: https://vmanage.acme.corp
sdwan_as: 65000                     # Uniform SD-WAN AS, every site, every region
campus_as: 65100                    # Uniform campus AS, every site, every region
dc_hub:                             # Read-only reference for regional topology
  site_id: 100                      # policies — NOT a managed resource outside
  system_ip_a: 10.0.0.1             # regions/dc-hub/
  system_ip_b: 10.0.0.2
```

## Common system profile parameters

Org-wide system configuration (AAA/TACACS, NTP, Banner, SNMP, Logging) lives
in `common/` at the repo root, one YAML file per feature. These values apply
to every site in every region. Site-specific overrides (e.g. SNMP location
string) are placed in a `system:` block **at the top** of each site YAML,
before `site_id`.

### `common/` YAML schemas

```yaml
# common/aaa.yaml
tacacs:
  servers:
    - address: 10.1.1.1
      port: 49
    - address: 10.1.1.2
      port: 49
  auth_order: [tacacs, local]       # authentication method order
  # key/secret: passed as sensitive Terraform variable, never in YAML

# common/ntp.yaml
servers:
  - address: 10.1.2.1
    vpn: 0
  - address: 10.1.2.2
    vpn: 0
timezone: UTC

# common/banner.yaml
motd: |
  ******************************************************************
  * AUTHORIZED ACCESS ONLY — All activity is logged and monitored. *
  ******************************************************************
login: "Authorized users only."

# common/snmp.yaml
version: v2c
communities:
  - name: acme-ro
    type: read-only
  - name: acme-rw
    type: read-write
trap_destinations:
  - address: 10.1.3.1
    vpn: 0

# common/logging.yaml
servers:
  - address: 10.1.4.1
    vpn: 0
    priority: informational
  - address: 10.1.4.2
    vpn: 0
    priority: informational
```

### Site YAML — `system:` block (site-specific overrides)

Always the **first block** in the site YAML, before `site_id`. Contains only
the fields that differ from `common/*.yaml`. Most sites only need `snmp.location`.

```yaml
# ── Site-specific system overrides ─────────────────────────────────────────
system:
  snmp:
    location: "NYC - 1 Main St - Floor 3"   # unique per site
    contact: "noc@acme.corp"                 # may be org-wide; omit if in common
# ───────────────────────────────────────────────────────────────────────────

site_id: 200
...
```

`modules/system-profile/` merges common values with site-level overrides to
produce the system parcels (`sdwan_system_aaa_feature`,
`sdwan_system_ntp_feature`, `sdwan_system_banner_feature`,
`sdwan_system_snmp_feature`, `sdwan_system_logging_feature`).

## Key Terraform patterns

### Per-site stack main.tf pattern (e.g. `regions/na/nyc/main.tf`)

```hcl
# regions/na/nyc/main.tf
locals {
  globals  = yamldecode(file("${path.module}/../../../globals.yaml"))
  site_cfg = yamldecode(file("${path.module}/../sites/nyc.yaml"))
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
  site_name          = "nyc"
  site_cfg           = local.site_cfg
  globals            = local.globals
  common             = local.common
  regional_policy_id = data.terraform_remote_state.policy.outputs.policy_id
}

module "policy_override" {
  count  = local.site_cfg.policy_override != null ? 1 : 0
  source = "../../../modules/policy-override"

  site_name       = "nyc"
  override_cfg    = local.site_cfg.policy_override
  config_group_id = module.site.config_group_id
}
```

The **policy stack** (`regions/na/policy/main.tf`) is simpler:

```hcl
locals {
  globals = yamldecode(file("${path.module}/../../../globals.yaml"))
  policy  = yamldecode(file("${path.module}/../policy.yaml"))
}

module "regional_policy" {
  source      = "../../../modules/policy-group"
  region_name = "na"
  policy_cfg  = local.policy
  dc_hub      = local.globals.dc_hub
}
```

```hcl
# regions/na/policy/outputs.tf
output "policy_id" {
  value = module.regional_policy.policy_id
}
```

`regions/dc-hub/` keeps the original combined pattern (policy + single site
in one stack) since there is only one hub site — splitting adds no benefit.

### Resource naming convention

All resources use `<module>_<site_name>` patterns. Use `for_each`, never
`count`. Mark password/PSK variables `sensitive = true`. Every module must
output at minimum `config_group_id` and `device_ids`.

### Terraform resources reference

| Purpose | Resource |
|---|---|
| Config group | `sdwan_configuration_group` |
| Transport feature profile | `sdwan_transport_feature_profile` |
| Service feature profile | `sdwan_service_feature_profile` |
| System feature profile | `sdwan_system_feature_profile` |
| **OMP settings** (device-wide, module/site) | `sdwan_system_omp_feature` — `advertise_ipv4_bgp` is the BGP→OMP direction, NOT per-VPN |
| WAN ethernet interface parcel | `sdwan_transport_wan_vpn_interface_ethernet_feature` |
| **VPN 0 container** (transport-side) | `sdwan_transport_wan_vpn_feature` |
| **VPN 10+ container** (service-side) | `sdwan_service_lan_vpn_feature` (valid range 1–65527 — never use for VPN 0) |
| **VPN 10+ BGP** (campus peering, per VRF) | `sdwan_service_routing_bgp_feature` — `omp` valid here for OMP→BGP; one resource per cEdge per VPN |
| OSPF parcel (service-side) | `sdwan_service_routing_ospf_feature` |
| OSPF parcel (transport-side, `private1` underlay) | `sdwan_transport_routing_ospf_feature` — one per transport feature profile; created when any transport entry carries an `ospf` block |
| Prefix list (route-map match) | `sdwan_policy_object_prefix_list` |
| Route-map parcel | `sdwan_service_route_policy_feature` |
| **CLI add-on profile** (UX2 escape hatch) | `sdwan_cli_feature_profile` — the profile container |
| **CLI add-on parcel** (raw IOS-XE CLI) | `sdwan_cli_config_feature` — parcel inside the CLI profile; holds the raw config |
| Topology policy (regional) | `sdwan_centralized_policy` |
| App-route policy definition | `sdwan_application_aware_routing_policy_definition` |
| Device attach | `sdwan_attach_feature_device_template` |

**VPN 0 is architecturally a transport-side resource, never a service-side
one.** `sdwan_service_lan_vpn_feature` only accepts VPN IDs 1–65527 — VPN 0
will always fail validation there. VPN 0's WAN interface parcel
(`sdwan_transport_wan_vpn_feature`) belongs in `modules/transport`. VPN 0 has
no campus BGP peering in this design — `sdwan_transport_routing_bgp_feature`
is not used. Only VPN 10 (and any future service VPNs) belong in
`modules/service`, using `sdwan_service_lan_vpn_feature` +
`sdwan_service_routing_bgp_feature`.

Route-map and policy-override resources should be created only when the
corresponding YAML fields are non-null (`~ = null = skip`). Use `for_each`
with a filtered map to avoid creating empty resources.

### Mandatory device-attach variables

When attaching a config group to a device (`sdwan_attach_feature_device_template`,
or the config-group equivalent), the `variables`/`device_variables` map MUST
include `pseudo_commit_timer = 300`. This is required — the attach fails
without it. It is easy to miss because it's not tied to any per-site YAML
field; it's a fixed device-attach parameter. Set it as a constant in the
attach resource (or as a defaulted module variable `pseudo_commit_timer`
defaulting to `300`) so every device attach across every site/region carries
it automatically. Do not make it a per-site YAML field — it's the same value
everywhere; bake it into the module so it can never be forgotten on a new site.

## Coding conventions

- **All resource names** follow `<module>_<site>` pattern using `var.site_name`.
- **No count** — always use `for_each` with meaningful keys (site names, VPN IDs).
- **Sensitive values** (passwords, PSKs): use `sensitive = true` in variable
  definitions; never log them in outputs.
- **Outputs**: every module exposes at minimum `config_group_id` and
  `device_ids` so the region's root module can surface them.
- **State**: local backend, one per region directory. Do NOT add a remote or
  shared backend that spans multiple regions — that would defeat the
  isolation this project is built around.
- **Never** create a root-level `main.tf`, `variables.tf`, or `outputs.tf` at
  the repo root that references multiple regions — every Terraform root
  module lives inside exactly one `regions/<name>/` folder.
- **Formatting**: always run `terraform fmt -recursive` before considering a
  task done.
- **Validation**: run `terraform validate` after every resource addition,
  from inside the relevant region's directory.

## Workflow

When working on this project, follow this order for any new site or feature:

1. Identify which region the change belongs to (or whether it's a shared
   module change — see "What NOT to do" for the extra caution that requires)
2. `cd regions/<name>/` — every subsequent command runs from here
3. Update or create the site YAML in `sites/`, or the region's `policy.yaml`
4. Extend the relevant shared module if a new parcel type is needed
5. Run `terraform plan -out=tfplan` and review the diff carefully — confirm
   it only touches the expected site(s) within this region
6. Never run `terraform apply` autonomously — always pause and show the plan
   first
7. After apply, verify in vManage that the config group shows "In sync"

## What NOT to do

- Do not create a root-level Terraform stack that spans multiple regions —
  every root module lives inside one `regions/<name>/` folder only.
- Do not create UX1 feature templates (`sdwan_feature_template`). This
  project is UX2-only. Two other provider resources are also UX1 and must
  never be used: `sdwan_cli_template_feature_template` and
  `sdwan_cli_device_template`. The UX2 equivalents are
  `sdwan_cli_feature_profile` + `sdwan_cli_config_feature`.
- Do not use `terraform taint` or `terraform state rm` without explicit user
  approval.
- Do not add a `lifecycle { prevent_destroy = true }` block without asking —
  it can block legitimate teardown of test sites.
- Do not interpolate device credentials into resource arguments — use
  variable references only.
- Do not give one region's Terraform configuration a file path, backend
  config, or state reference that touches another region's directory.
- Do not let `regions/dc-hub/` be modified as a side effect of a regional
  change — it is managed only from inside its own directory.
- When editing a **shared module** (`modules/*`), be aware the diff will
  appear in every region that uses it on their next `plan`. Call this out
  explicitly to the user before proceeding — it is the one case where a
  single change legitimately touches multiple regions' states (each region
  still applies independently, but all of them will show the same diff).
- Do not commit `terraform.tfvars`, `*.tfstate`, or `.terraform/` from any
  region directory — they are gitignored.

## Useful commands

```bash
# Always start by moving into the target region
cd regions/na

# Initialise (first time, or after provider version bump) — per region
terraform init -upgrade

# Plan/apply only ever affects this region's state
terraform plan -out=tfplan
terraform apply tfplan

# Plan against a specific site within this region only
terraform plan -target='module.site["nyc"]'
terraform apply -target='module.site["nyc"]'

# Format and validate (run from inside the region directory)
terraform fmt -recursive
terraform validate

# Inspect state for one site within this region
terraform state list | grep nyc
terraform state show 'module.site["nyc"].module.config_group.sdwan_configuration_group.this'
```

## Provider documentation shortcut

When looking up a resource or data source, check:
https://registry.terraform.io/providers/CiscoDevNet/sdwan/latest/docs

Search by resource name, e.g. `sdwan_transport_wan_vpn_interface_ethernet_feature`
for WAN ethernet interface parcels.
