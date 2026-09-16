# BGP Redistribution + Route-Policy Design
**Date:** 2026-08-06  
**Scope:** All sites (BEL DC hub + all branch variants)  
**Status:** Approved, pending implementation

---

## Decisions

| Question | Decision |
|---|---|
| Redistribution directions | Both (OMP→BGP and BGP→OMP) at all sites |
| Route-map capability | Full (prefix filtering + attribute manipulation) |
| Deployment | Template hooks present; all values commented placeholders |
| Hub vs. branch structure | Hub (BEL): route-maps defined + neighbor linkage. Branches: raw redistribute, no route-map |
| Route-map definition | CLI add-on — raw IOS-XE in `templates/dc/cli.yaml` |
| Neighbor→route-map linkage | Data model — `route_policy_in/out_variable` on `ipv4_neighbors[]` in `dc/service.yaml` |
| Template file split | No new files — route-map CLI appended to existing `dc/cli.yaml`; no generate.py change |

---

## Architecture

```
Campus SDA (branches)       SD-WAN fabric (OMP)        Campus DC-core (BEL)
         │                         │                            │
BGP→OMP  │   (campus routes        │        OMP→BGP            │
         │    into overlay)        │   (spoke routes toward     │
         ▼                         ▼    DC core + route-policy) ▼
[branch bgp_features]           [OMP]      [dc bgp_features]
  redistribute omp                         redistribute omp
  redistribute connected                   redistribute connected
  propagate_community: true                propagate_community: true
  no route-map                             route_policy_out_variable (commented)
                                           route_policy_in_variable  (commented)
                                                    │
                                           [dc cli.yaml — CLI add-on]
                                             route-map RT-POL-OUT-BEL
                                             route-map RT-POL-IN-BEL
```

**OMP → BGP:** `redistribute: [{protocol: omp}, {protocol: connected}]` in `bgp_features` of all service templates. DC hub also carries commented `route_policy_out_variable` on its core neighbor (data model linkage).

**BGP → OMP:** `advertise_ipv4_bgp: true` in `_shared/system.yaml` OMP parcel (was `false`). Fabric-wide; same for all variants.

**`propagate_community: true`** required on all sites. SDA uses BGP community `955999` to tag routes it received from SD-WAN; its `DROP_FABRIC_ROUTES in` map drops anything carrying that community back from SD-WAN. Without `propagate_community`, communities do not survive OMP→BGP redistribution and the loop guard breaks silently.

**Route-map blocks (DC hub only):** defined as raw IOS-XE CLI in the existing `templates/dc/cli.yaml` CLI add-on profile. Route-map config and port-channel config are separate IOS-XE config sections — no conflict within the same `cli_configuration` string. No new file, no generate.py change.

**Neighbor linkage (DC hub only):** `route_policy_in/out_variable` on the `ipv4_neighbors[]` entry in `dc/service.yaml` — data model, commented by default. Activating is a two-step: uncomment the variable reference in the template AND uncomment the variable value in `bel.yaml`.

---

## Changes per file

### `templates/_shared/system.yaml`
- `advertise_ipv4_bgp: false` → `advertise_ipv4_bgp: true`

### `templates/branch/service.yaml` and `templates/branch/service-routed.yaml`
Add to `bgp_features[0]`:
```yaml
redistribute:
  - protocol: omp
  - protocol: connected
propagate_community: true
```
Add to each `ipv4_neighbors[]` entry:
```yaml
fall_over_bfd: true
send_community: both
```
No route-map reference on branches.

### `templates/dc/service.yaml`
Same redistribution and per-neighbor additions as branches. Add commented route-policy variable references on the core neighbor:
```yaml
ipv4_neighbors:
  - address_variable: bgp_neighbor_core
    remote_as_variable: bgp_neighbor_remote_as
    fall_over_bfd: true
    send_community: both
    # route_policy_in_variable: bgp_policy_in    # uncomment + define in bel.yaml to activate
    # route_policy_out_variable: bgp_policy_out  # uncomment + define in bel.yaml to activate
```

### `templates/dc/cli.yaml`
Append a route-map CLI block to the existing `cli_configuration` string.
Route-map names and all match/set values are device variables (`{{variable_name}}` syntax).
Block is commented out in the CLI string by default — uncommented when ready to deploy.

Structure (two maps: inbound and outbound, multi-sequence):
```
! --- BGP route-policy (uncomment to activate) ---
! route-map RT-POL-IN-{{site_code}} permit 10
!  match ip address prefix-list {{bgp_policy_in_pfx}}
!  set local-preference {{bgp_policy_in_local_pref}}
! route-map RT-POL-IN-{{site_code}} deny 65535
!
! route-map RT-POL-OUT-{{site_code}} permit 10
!  match ip address prefix-list {{bgp_policy_out_pfx_specific}}
!  set metric {{bgp_policy_out_med}}
!  set as-path prepend {{bgp_policy_out_as_prepend}}
! route-map RT-POL-OUT-{{site_code}} permit 20
!  set metric {{bgp_policy_out_med}}
! route-map RT-POL-OUT-{{site_code}} deny 65535
```

### `values/bel.yaml`
Add commented variable block under each router's BGP section:
```yaml
    # BGP route-policy variables — uncomment to activate (both routers)
    # bgp_policy_in: RT-POL-IN-BEL
    # bgp_policy_out: RT-POL-OUT-BEL
    # bgp_policy_in_pfx: ~                       # prefix-list name for inbound match
    # bgp_policy_in_local_pref: '100'
    # bgp_policy_out_pfx_specific: ~             # prefix-list name for specific-prefix seq
    # bgp_policy_out_med: '1000'
    # bgp_policy_out_as_prepend: '655370 655370'
```

---

## Schema risk — verify before implementing

Route-map blocks are CLI add-on — zero schema risk there. Remaining unverified keys in the **data model** (`sdwan_features_service.tf`):

| Key | Location | Risk |
|---|---|---|
| `redistribute[].protocol` | `bgp_features` | High — format unknown |
| `propagate_community` | `bgp_features` | High — may not exist in module |
| `fall_over_bfd` | `ipv4_neighbors[]` | Medium — key name unknown |
| `send_community` | `ipv4_neighbors[]` | Medium — accepted values unknown |
| `route_policy_in/out_variable` | `ipv4_neighbors[]` | High — mechanism unverified |

If any key is absent from the module, fall back to CLI add-on for that attribute (append to the same `cli_configuration` string as the route-map block).

---

## Reference: actual IOS-XE configs

**SD-WAN side (branch edge):**
```
router bgp 655370
 address-family ipv4 vrf 10
  bgp router-id 10.99.209.17
  redistribute connected
  redistribute omp
  propagate-community
  neighbor 10.0.0.1 remote-as 65537
  neighbor 10.0.0.1 fall-over bfd
  neighbor 10.0.0.1 activate
  neighbor 10.0.0.1 send-community both
  neighbor 10.0.0.1 route-map OMP_TO_BGP_1000_MED out
  distance bgp 20 200 20

route-map OMP_TO_BGP_1000_MED permit 1
 match ip address prefix-list LO_BB_PFX
 set metric 1000
 set as-path prepend 655370 655370 655370 655370 655370
route-map OMP_TO_BGP_1000_MED permit 11
 set metric 1000
route-map OMP_TO_BGP_1000_MED deny 65535
```

`distance bgp 20 200 20` — not yet modelled; add if NaC schema supports it, otherwise CLI add-on.

**SDA side (campus edge, not managed here):**
- `DROP_FABRIC_ROUTES in` — drops routes tagged with community 955999 (loop prevention)
- `RM-OUT out` — filters what campus advertises to SD-WAN
- These are SDA policy, outside this project's scope.
