---
applyTo: "regions/*/sites/*.yaml"
---

# Site YAML authoring rules

## File location

Site files live inside their region's folder: `regions/<region>/sites/<site>.yaml`.
A site's region is determined entirely by which folder it's placed in — there
is no `region:` field inside the site YAML itself.

## YAML documentation standard

Every site YAML must be **self-documenting**. Use section-header comment
blocks to separate logical areas, and inline comments to explain non-obvious
values. Future maintainers must be able to understand the site's topology,
protocols, and intent without reading any other file.

Rules:
- Section headers: `# ── <Section Name> ──────────` (at least 60 chars wide)
- Every key whose value is not self-explanatory gets a trailing `# comment`
- VLAN numbers, IP addresses, OSPF areas, and AS numbers always get a comment
  explaining what they connect to or what role they play
- `~` (null) values get a comment explaining why they are absent
- The `system:` block is always the first section, before `site_id`

## Required top-level keys

**First block:** `system:` (site-specific overrides — always first, before `site_id`)

**Remaining keys (in order):** `site_id`, `system_ip_a`, `system_ip_b`,
`hostname_a`, `hostname_b`, `chassis_a`, `chassis_b`, `transports`,
`tloc_ext` (always present, may be `~`), `cli_addon` (always present, may be `~`),
`route_maps`, `service_vpns`, `omp_advertise_bgp`, `policy_override` (may be `~`)

## site_id uniqueness

`site_id` must be unique **globally across all regions**, not just within
one region's folder. Before creating a new site file, check every
`regions/*/sites/*.yaml` file to find the next available ID — not just the
files in the current region.

## Transport keys (color-keyed map)

`transports` is a MAP keyed by vManage TLOC color, NOT a fixed set of named
slots. Valid keys are the real color names: `custom1` (ISP-A), `custom2`
(ISP-B), `private1` (own MPLS). Declare only the colors this cEdge actually
has — a full branch has all three, an internet-only site has just `custom1`
and `custom2`, the DC has `custom1`/`custom2`/`private1`. Never invent other
color keys.

Each entry needs `interface`, plus one of:

- `dhcp: true` — ISP/internet circuits (`custom1`, `custom2`). No IP address field.
- `ip`/`mask` plus an `ospf` block — MPLS circuits (`private1`). OSPF runs as the
  underlay protocol between the cEdge and the PE router. No `gateway` field; OSPF
  handles routing. The `ospf` block requires at minimum `area` (integer).
- `ip`/`mask`/`gateway` — static routing. Valid schema option but not used for
  `private1` in this design (OSPF is the MPLS underlay).

In this design: `custom1` and `custom2` always use `dhcp: true`; `private1`
always uses the `ospf` block. The `private2` TLOC is derived from the peer's
`private1` via TLOC-EXT and therefore inherits its OSPF underlay — it has no
entry in `transports` and no separate OSPF configuration.

Do NOT add a `private2` key — `private2` is the peer's MPLS arriving via
TLOC-EXT (the `tloc_ext` block), a derived TLOC, never a directly-configured
transport. `transports` holds only this cEdge's own circuits.

**Color keys are immutable once a site is deployed.** They become Terraform
state addresses (`transports["private1"]`). Renaming one is a destroy+create
that flaps the TLOC. Treat them like primary keys — never rename in place.

## Color values (exact strings defined in vManage)

- ISP-A: `custom1`
- ISP-B: `custom2`
- Own MPLS: `private1`
- Peer MPLS via TLOC-EXT: `private2` (derived — not a transport key, result
  of TLOC-EXT; only exists at sites that have a `tloc_ext` block)

Do not change these color names — they are real vManage TLOC color definitions.

## tloc_ext keys (OPTIONAL)

`tloc_ext` is optional. Set it to `~` (null) for any site that doesn't use
TLOC extension — notably the DC hub, where an upstream fusion router means
each cEdge reaches MPLS directly and there is no peer MPLS to extend. A DC
cEdge advertises only 3 TLOCs (`custom1`, `custom2`, `private1`), never
`private2`. Never add a `tloc_ext` block to the DC hub site file.

When `tloc_ext` IS present (branches needing peer-MPLS sharing), it must
contain: `port`, `sub_if_extend`, `sub_if_receive`. Both sub-interfaces must
be defined — they are present on **both** cEdges at the site. `sub_if_extend`
carries own `private1` outward; `sub_if_receive` receives the peer's.

Note: the `tloc_ext` shared physical port is unrelated to the campus-facing
port used by VPN 0 / VPN 10 BGP — those still share their own separate port
(`campus_interface.interface`), and VPN 0 is never on a different physical
interface from VPN 10.

## route_maps

`route_maps` is a top-level map in the site YAML (sibling to `service_vpns`).
Define any number of named policies; each becomes one
`sdwan_service_route_policy_feature` resource when at least one field is
non-null. Peers reference entries by name via `route_map_in`/`route_map_out`.

Valid fields per entry: `prefix_list`, `set_local_pref`, `set_med`,
`set_community`, `as_path_prepend`. Set unused fields to `~`. Omit
`route_maps` entirely (or set to `{}`) when no route-map policies are needed
at this site.

## service_vpns / campus peering rules

`service_vpns` must contain an entry for VPN 0 and an entry for VPN 10.

**VPN 0 entry** — transport-only. Must NOT contain `campus_interface` or any
routing block. VPN 0 is the underlay; it has no campus peering and no route
exchange with the campus switch. Only `vpn: 0` and `name: TRANSPORT` are
required.

**VPN 10 entry** — service side. Must contain `campus_interface`. There is no
`routing: bgp` field at the VPN level — the campus protocol is inferred from
which sub-block is non-null on each cEdge.

`campus_interface` structure:
- `port`: the physical trunk interface name (e.g. `GigabitEthernet6`). The
  actual sub-interface on the cEdge is derived as `<port>.<vlan>`.
- `vrfs`: list of VRF peering blocks. Must contain CORP and INFRA (or
  whatever VRFs are active at this site). Each VRF entry:
  - `name`: unique key within the vrfs list — used as the `for_each` key
    in Terraform resource addresses. Do not rename after deployment.
  - `cedge_a` and `cedge_b`: **both always required**. Each has its own
    `vlan`, `ip`, `mask`, plus exactly one of:
    - `bgp` sub-block (non-null) + `ospf: ~` — BGP campus peering.
      `bgp` contains: `neighbor_ip`, `route_map_in`, `route_map_out`.
      `route_map_in`/`route_map_out` reference names from the `route_maps`
      library above, or `~` for no policy. Per-cEdge — different policies
      can be applied independently to cEdge-A and cEdge-B.
    - `ospf` sub-block (non-null) + `bgp: ~` — OSPF campus peering.
      `ospf` contains: `area` (integer). No `neighbor_ip` or route-maps —
      OSPF uses dynamic discovery within the area.
    cEdge-A and cEdge-B **always have different VLANs** for the same VRF —
    each connects to a different SVI on the campus L3 switch. Never share a
    VLAN or neighbor IP between the two cEdges for the same VRF.
  - `redistribute_omp`: boolean, per VRF, not per cEdge. Controls
    OMP→campus-protocol redistribution in the BGP or OSPF feature resource.

There is no `redistribute_bgp` field anywhere in `service_vpns` — the
campus→OMP direction is handled by the separate top-level `omp_advertise_bgp`
field, never nested inside a VPN or VRF entry.

Do not invent per-site AS numbers — `sdwan_as` and `campus_as` come from
`globals.yaml`, never duplicated in site YAML.

## system (top-level, first block)

Always the first block in the site YAML, before `site_id`. Contains only
values that differ from `common/*.yaml`. Most sites only need `snmp.location`.
Omit any field that matches the common default — the module merges common
values with these overrides (site wins on conflict).

```yaml
# ── Site-specific system overrides ─────────────────────────────────────────
system:
  snmp:
    location: "NYC - 1 Main St - Floor 3"   # physical location string (MIB-II sysLocation)
    contact: "noc@acme.corp"                 # omit if defined org-wide in common/snmp.yaml
# ───────────────────────────────────────────────────────────────────────────
```

Do NOT put TACACS keys, NTP auth keys, or SNMP community strings here —
those are credentials and must be Terraform sensitive variables, not YAML.

## cli_addon (top-level, optional)

Set to `~` for all branch sites. Only used when a site needs IOS-XE
configuration that has no native UX2 parcel — currently the DC hub, whose
cEdges connect to the campus switch via a port-channel on the service side.

When non-null, must contain a `port_channel` sub-block:

```yaml
cli_addon:                        # ~ for branch sites
  port_channel:
    id: 10                        # Logical interface: Port-channel<id>
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
    as_number: "10.10"            # router bgp AS for fall-over bfd — MUST match
                                  # globals.yaml.sdwan_as in the notation IOS-XE
                                  # displays it; mismatch creates a second BGP process
  buf_filter:
    host_a: 10.99.14.3            # BUF-FILTER ACL endpoints (were hardcoded in UX1)
    host_b: 10.22.108.4
  pnp_startup_vlan: 62            # pnp startup-vlan (was hardcoded in UX1)
```

When `cli_addon` is non-null, `campus_interface.port` in the VPN 10 entry
must be set to the derived port-channel name (`Port-channel10` for `id: 10`),
not a physical interface.

`private_interface.name` is NOT a field — the interface name is reused from
`transports.private1.interface` (no duplication). BGP neighbor IPs are NOT
in `cli_addon` — reused from `service_vpns[10].campus_interface.vrfs[*].cedge_a/b.bgp.neighbor_ip`.

Do NOT use `sdwan_cli_template_feature_template` or `sdwan_cli_device_template`
to implement this — both are UX1. The UX2 resources are
`sdwan_cli_feature_profile` + `sdwan_cli_config_feature`.

## omp_advertise_bgp (top-level, required)

A single boolean at the site YAML's top level — sibling to `service_vpns`,
never nested inside it. Maps to `sdwan_system_omp_feature.advertise_ipv4_bgp`,
a device-wide setting applied identically to both cEdges. This is the
campus→OMP direction; do not confuse it with `redistribute_omp` (the
OMP→campus direction, which IS per-VRF and lives inside each VRF block).
OSPF sites may also need `advertise_ipv4_ospf` on the same resource.

## policy_override

Optional, additive-only block. Set to `~` when the branch uses only the
regional baseline from `regions/<region>/policy.yaml`. When present, it
must contain only `qos` and/or `app_route` sub-blocks — it layers on top
of the regional policy, never replaces it. Do not add a `topology` key
here; topology is region-wide only.

Any DSCP value inside a `qos` sub-block must be a **decimal integer**, never
a PHB keyword (no `ef`/`af31`/`default` — use 46/26/0). Same rule as the
regional QoS classes.

## File naming convention

`<city-or-location>.yaml` for branch sites, `dc-hub.yaml` for the hub.
Lowercase, hyphens only (no underscores, no spaces).

## Branch site variants

Two variants cover all branch topologies. The DC hub uses its own separate YAML
file and schema. The only fields that differ between variants are `transports`
and `tloc_ext` — all other fields are structurally identical.

### Variant A — full branch (dual internet + MPLS + TLOC-EXT)

Use when the site has two ISP circuits and one MPLS circuit, and the two cEdges
share their MPLS via TLOC-EXT. Produces 4 TLOCs per cEdge.

```yaml
site_id: 200
system_ip_a: 10.0.1.1
system_ip_b: 10.0.1.2
hostname_a: nyc-cedge-01
hostname_b: nyc-cedge-02
chassis_a: "CSR1000V-..."
chassis_b: "CSR1000V-..."

transports:
  custom1:
    interface: GigabitEthernet2
    dhcp: true
  custom2:
    interface: GigabitEthernet3
    dhcp: true
  private1:
    interface: GigabitEthernet4
    ip: 192.168.1.1
    mask: 255.255.255.252
    ospf:
      area: 0

tloc_ext:
  port: GigabitEthernet5
  sub_if_extend:
    sub_interface: GigabitEthernet5.101
    vlan: 101
  sub_if_receive:
    sub_interface: GigabitEthernet5.102
    vlan: 102

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
            bgp:                    # non-null = BGP campus peering; ~ for OSPF sites
              neighbor_ip: 10.10.1.2
              route_map_in: ~
              route_map_out: ~
            ospf: ~                 # non-null = OSPF campus peering; ~ for BGP sites
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

### Variant B — internet-only branch (dual internet, no MPLS)

Use when the site has only ISP circuits (no MPLS). `tloc_ext: ~` must be set —
it produces zero TLOC-EXT resources. 2 TLOCs per cEdge: `custom1`, `custom2`.

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

tloc_ext: ~

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
