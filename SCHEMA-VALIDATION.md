# Schema Validation — templates/ vs nac-sdwan 1.4.0 (actual module source)

Date: 2026-07-24. Validated against the module source downloaded by
`terraform init` into `sites/bxt/.terraform/modules/sdwan/` (registry
`netascode/nac-sdwan/sdwan` 1.4.0, provider `ciscodevnet/sdwan` 0.11.3).
Method: read the module's `.tf` files and traced every YAML path it
actually consumes (`local.model.sdwan.*`, `try(each.value.<key>, ...)`).

**Verdict: the overall concepts map well, but nearly every container key
and the entire variable mechanism must change.** Details below, worst
first.

---

## 1. Structural mismatches (breaking — nothing works until fixed)

### 1.1 Everything must nest under a top-level `sdwan:` key

The module reads `local.model.sdwan.<...>` exclusively. Our templates
emit top-level keys (`system_feature_profiles:`, `config_groups:`, ...)
that the module never looks at — today's YAML would produce **zero
resources** and an empty plan.

### 1.2 Real container paths

| Ours (invented) | Module (actual) |
|---|---|
| `system_feature_profiles:` | `sdwan.feature_profiles.system_profiles[]` |
| `transport_and_management_feature_profiles:` | `sdwan.feature_profiles.transport_profiles[]` |
| `service_feature_profiles:` | `sdwan.feature_profiles.service_profiles[]` |
| `cli_feature_profiles:` | `sdwan.feature_profiles.cli_profiles[]` |
| `policy_object_profiles:` (list) | `sdwan.feature_profiles.policy_object_profile` (**one single global object** — see §5) |
| `policy_groups:` | `sdwan.policy_groups[]` (different shape — see §5) |
| `config_groups:` | `sdwan.configuration_groups[]` (different shape — see §4) |
| `aaa_server_groups:` (own file) | does not exist — TACACS nests inside the aaa parcel (see §2) |
| `sites:` (site-values.yaml) | `sdwan.sites[].routers[]` (different shape — see §4) |

### 1.3 No `parcels:` wrapper

Parcels are direct keys on the profile object:
`system_profiles[].{aaa,banner,basic,bfd,logging,ntp,snmp,omp,global,...}`.
Our `parcels:` nesting level must be removed everywhere.

### 1.4 Device variables use `<field>_variable:` keys, not `{{...}}` values

For every field `x` the module accepts a sibling `x_variable:`; it wraps
the value in `{{...}}` itself
(`try("{{${...x_variable}}}", null)`). Writing `ipv4_address: "{{vpn0_inet1_ip}}"`
sends a literal brace-string as a constant. Correct form:

```yaml
# wrong (ours today)              # right (module)
ipv4_address: "{{vpn0_inet1_ip}}"   ipv4_address_variable: vpn0_inet1_ip
```

Every `{{var}}` reference in `templates/` must convert to the
`_variable:` form. The variable names themselves (matching
`device_variables` keys) are fine.

---

## 2. System profile (templates/_shared/system.yaml + aaa_tacacs.yaml)

| Ours | Module | Status |
|---|---|---|
| `basic.console_baud_rate` | same | ✅ |
| `basic.clock_timezone` | `basic.timezone` | ✗ rename |
| — | `basic.latitude` / `basic.longitude` (GPS lives here; supports `_variable`) | add, wire `gps_lat`/`gps_lon` |
| — | `basic.port_offset` (supports `_variable`) | add, wire `port_offset` |
| `aaa.auth_order` | `aaa.auth_order` | ✅ |
| `aaa.auth_fallback` | **not found** in module | ✗ drop (no such knob) |
| `aaa_server_groups[]` (separate file, `name`/`type`/`vpn`/`source_interface`/`servers[]`) | `aaa.tacacs_groups[]` with `vpn`, `source_interface`, `servers[] {address, key, port, timeout}` | ✗ restructure |
| `...groups[].name: tacacs-10` | **auto-derived**: `group_name = "tacacs-${vpn}"` | ✗ drop `name` — vpn 10 → `tacacs-10`, vpn 512 → `tacacs-512` (matches the live fabric naming exactly!) |
| `servers[].encrypted_key` | `servers[].key` (or `key_variable`) | ✗ rename |
| `banner.motd` | `banner.motd` (also `banner.login`) | ✅ |
| `bfd.multiplier` / `bfd.poll_interval` | same | ✅ |
| `logging.disk_enabled` | **not found** (`disk_file_rotate`/`disk_file_size` exist) | ✗ drop or map |
| `logging.servers[]` | `logging.ipv4_servers[]` | ✗ rename |
| `...servers[].address` | `.hostname_ip` | ✗ rename |
| `...servers[].priority` | `.severity` | ✗ rename |
| `...servers[].vpn` | `.vpn_id` | ✗ rename |
| `...servers[].source_interface` | same | ✅ |
| `ntp.servers[].hostname` | `.hostname_ip` | ✗ rename |
| `ntp.servers[].vpn` | `.vpn_id` | ✗ rename |
| `ntp.servers[].source_interface` | same | ✅ |
| `snmp.enabled` | no such field (`snmp.shutdown` exists, inverted) | ✗ replace |
| `snmp.contact` | `snmp.contact_person` | ✗ rename |
| `dns:` parcel | **does not exist in system profile** — DNS is per-VPN: `wan_vpn.ipv4_primary_dns_address` / `ipv4_secondary_dns_address` (and same on `management_vpn`, `lan_vpns[]`) | ✗ move to transport/service |

Impact on `globals.yaml`: `aaa.auth_fallback` and `logging.disk_enabled`
have no module equivalent; `dns.servers` moves conceptually into the
transport template; inner key renames (`hostname`→`hostname_ip`,
`vpn`→`vpn_id`, `priority`→`severity`) needed in the ntp/logging lists.

---

## 3. Transport profile (transport-a/b.yaml, dc/transport.yaml)

| Ours | Module | Status |
|---|---|---|
| `wan_vpn:` (object) | `wan_vpn:` (object) | ✅ concept |
| `wan_vpn.vpn_id: 0` | no such field (WAN VPN is implicitly 0) | ✗ drop |
| `wan_vpn.dns.primary/secondary` | `wan_vpn.ipv4_primary_dns_address` / `ipv4_secondary_dns_address` | ✗ rename |
| `wan_vpn.routes[] {prefix, next_hops[]}` | `wan_vpn.ipv4_static_routes[] {network_address, subnet_mask, next_hops[] {address}}` | ✗ restructure — CIDR prefix splits into address+mask |
| `wan_vpn.interfaces[]` | `wan_vpn.ethernet_interfaces[]` | ✗ rename |
| `interface.name/shutdown/ipv4_address/bandwidth_downstream/shaping_rate` | same (each with `_variable` twin) | ✅ names, ✗ mechanism (§1.4) |
| `interface.description` | `interface.description`? — not confirmed in grep; verify when rewriting | ⚠ |
| `tunnel_interface.color` | same (+`color_variable`) | ✅ |
| `tunnel_interface.encapsulation: ipsec` | `tunnel_interface.ipsec_encapsulation: true` | ✗ restructure |
| `tunnel_interface.preference` | `tunnel_interface.ipsec_preference` (+`_variable`) | ✗ rename |
| `interface.tloc_extension` | same (+`_variable`) | ✅ |
| `ospf:` (inline parcel) | separate `profile.ospfs[]`-style feature referenced **by name** via `wan_vpn.ospf: <name>` | ✗ restructure (verify exact container key when rewriting) |
| `management_vpn:` (object) | `management_vpn:` (object), with `ethernet_interfaces[]` and `ipv4_static_routes[]` same as wan_vpn | ✅ concept, same inner renames |
| `management_vpn.vpn_id: 512` | no such field (management VPN is implicitly 512) | ✗ drop |
| `transports:` map (old design, still in dc/transport? no — removed) | n/a | — |

---

## 4. Config groups & device attach (config-group.yaml + site-values.yaml)

Module shape:

```yaml
sdwan:
  configuration_groups:
    - name: CG-BXT
      system_profile: SYS-BXT        # by-name references, one per type
      transport_profile: TRANS-BXT   # NOT a `profiles:` list
      service_profile: SVC-BXT
      cli_profile: CLI-BXT           # dc only
      # NO policy_group here — policy group is per-router (below)
  sites:
    - routers:
        - chassis_id: <REAL-CHASSIS-ID>     # REQUIRED — we don't have these yet!
          configuration_group: CG-BXT       # per-router, by name
          configuration_group_deploy: false # deploy gate (defaults false)
          policy_group: PG-BXT              # per-router, by name
          device_variables:                 # flat map name -> value
            host_name: SD-WAN01             # identity fields are variables too
            ...
```

Deltas from our `build_site_values_yaml()` output:

- `config_groups[].profiles:` list → per-type named keys; `policy_group`
  moves out of the config group onto each router.
- Our `sites[].{site_id, config_group, policy_group}` site-level keys →
  all per-router; no site-level `site_id` key consumed by the module
  (site-id travels as a device variable).
- Our `devices[] {name, hostname, system_ip, site_id, variables}` →
  `routers[] {chassis_id, configuration_group, policy_group,
  device_variables}` — identity fields fold INTO `device_variables`.
- **`chassis_id` is required and we have no chassis IDs** — they're the
  real device serials from vManage; the anonymised exports' `csv-deviceId`
  column was skipped by `csv_to_values.py` (`SKIP_COLS`). Needs a
  decision: re-extract from a non-anonymised export or add placeholders.
- **Correction after live validation (2026-07-27):** The NaC module has no
  dedicated `pseudo_commit_timer` argument because config-group device
  variables are a generic name/value map. The Cisco provider explicitly
  recognizes `pseudo_commit_timer` as a system variable, its config-group
  examples supply value `0`, and live vManage requires it. It must therefore
  be present in every router's `device_variables`. The per-router `deploy`
  boolean generated from `configuration_group_deploy` remains a separate
  deploy gate; the two fields are not substitutes.

---

## 5. Policy (templates/_shared/policy.yaml)

- `sdwan.policy_groups[]` exists but references only
  `application_priority` and `ngfw_security` profiles by name — there is
  no `policy_object_profile` link on a policy group.
- **`feature_profiles.policy_object_profile` is a single, global object**
  (`count = contains(keys(...))`, not `for_each`) — vManage only allows
  one policy-object profile per tenant. Our per-site `PO-__SITE__` design
  is impossible; policy objects (class maps, prefix lists, ...) must
  become one shared fabric-wide object (move from `_shared/policy.yaml`'s
  per-site pattern to a genuinely global one).
- QoS maps / app-priority policy live in
  `feature_profiles.application_priority_profiles[]` (see
  `sdwan_features_application_priority.tf`) — not modelled yet; our
  `qos_map` under the policy-object profile is in the wrong place.
  Field-level mapping still to do when rewriting policy.yaml.

## 6. Service profile (service.yaml) — for completeness

- `lan_vpn:` (ours, singular) → `lan_vpns[]` (list) with `vpn_id` ✅ and
  a required `name`.
- Interfaces split by type: `ethernet_interfaces[]` (Loopback10 goes
  here), `svi_interfaces[]` (Vlan62/Vlan253/CORP/INFRA SVIs).
- BGP/OSPF are separate named features (`profile.bgps[]`/`ospfs[]`-style)
  referenced from the VPN via `lan_vpn.bgp: <name>` / `lan_vpn.ospf:
  <name>` — not inline blocks.
- DHCP is `profile.dhcp_servers[]` (`pool_network_address`,
  `pool_subnet_mask`, `default_gateway`, each with `_variable`),
  associated to an SVI by name — our inline `dhcp_server:` under the
  interface must split out. Note: pool is address+mask, not CIDR.
- VRRP on SVI: fields exist on the SVI feature (not fully mapped yet).
- Switchport: `profile.switchport_features[]` (ours `switchport:` ✗).

## 7. CLI profile (dc/cli.yaml)

`cli_profiles[].config.cli_configuration` (string). Ours:
`parcels.config.cli` → rename, drop wrapper. ✅ concept otherwise.

---

## What survives unchanged

Concept-level: profile-per-type layout, one config group per site,
per-device variables for everything asymmetric, TACACS group per variant
(now expressed inside aaa), management VPN 512 for DC, SVI/DHCP/VRRP/
BGP/OSPF modelling, CLI escape hatch for the DC LAG. Variable NAMES in
`values/*.yaml` are all reusable as-is. The generate.py pipeline
(`__SITE__`, `__GLOBAL:`, per-site rendering) is unaffected — only the
YAML content it renders must change.

## Status: rewrite APPLIED 2026-07-24

Everything below was implemented the same day: all templates rewritten to
the validated structure, `build_site_values_yaml()` emits the
`sdwan.sites[].routers[]` shape with deploy gates, `globals.yaml`
adjusted (aaa moved to variant files, dns/disk_enabled/pseudo_commit_timer
removed, inner keys renamed), values files converted to address-only IPs
with `chassis_id`/`bgp_as_number` placeholders, CLAUDE.md hard rule
updated.  Offline verification: YAML merge accepted by utils 1.0.2
(merge-by-name confirmed), `validate_model.py` cross-checks pass,
`terraform plan` reaches provider authentication.  Remaining: real
chassis IDs, app-priority/QoS modelling, SNMPv3 detail, BGP as_number +
route policies, live-vManage plan.

## Live config-group validation findings — 2026-07-27

A BXT apply reached vManage but configuration-group device-variable
validation failed with `SCHVALID0001`. Tracing the rejected variable names
through nac-sdwan 1.4.0 identified these source-model issues:

- `bgp_features[].neighbors` is not consumed by module 1.4.0. IPv4 peers
  must use `bgp_features[].ipv4_neighbors`; otherwise the device variables
  are submitted at attach time without corresponding BGP parcel variables.
- A subsequent BXT apply reached the BGP parcel update and vManage required
  `data.neighbor[0].remoteAs` and `data.neighbor[1].remoteAs`. Every
  `ipv4_neighbors[]` entry therefore needs `remote_as` or
  `remote_as_variable`. The UX1 export confirms both peers used one constant
  `bgp_neighbor_remote_as`, but its anonymized value is `BGP_REMOTE_AS`.
  The field is now wired as `remote_as_variable` and emitted from each active
  site's `values/<site>.yaml`; the placeholder scan deliberately blocks a
  safe deployment until the real remote AS replaces `BGP_REMOTE_AS`.
  For BXT, the SDA neighbor AS was confirmed as `65537` on 2026-07-27 and is
  now set for both routers. BEL remains independently unresolved.
- Provider Ethernet resources require `ipv4_address_type: static` when
  `ipv4_address_variable` is present. Omitting the type caused recurring
  Terraform drift (`static -> null`) and left the address variables outside
  the configuration-group schema.
- Device variables must contain only identity variables and names referenced
  by active feature parcels. Unmodelled ThousandEyes (`te_*`) and outbound
  BGP policy variables were rejected and have been removed from active BXT
  values until their parcels are implemented.
- Address values remain address-only; masks are separate template fields.
  SVI names use the IOS-XE `Vlan<number>` format.
- `pseudo_commit_timer: 0` is required in every router's device variables as
  a config-group system variable. UX2 deploy control independently remains
  `configuration_group_deploy`.

Latest live result: after all declared feature variables were corrected,
vManage returned `Required But Missing Attributes: ["pseudo_commit_timer"]`
during the configuration-group device-variable PUT. Provider source confirms
this is expected config-group system-variable behavior, not stale UX1
attachment metadata. Value `0` is now emitted per router from active values
files and enforced by `validate_model.py`.

The source fixes are guarded by `validate_model.py`. Post-fix generation,
Terraform validation, and a live plan/apply remain pending as of this entry;
no successful deployment is claimed here.

**Superseded 2026-07-29:** the live BXT deployment has since succeeded —
`sites/bxt/terraform.tfstate` shows CG-BXT/PG-BXT and all feature parcels
applied cleanly against vManage (real chassis IDs, `bgp_neighbor_remote_as`
= 65537, `pseudo_commit_timer: 0` accepted, deploy gates still `false`).
The deployed lab site-id is **3** (per-router device variable), not the
1405 from the UX1 export; `generate.py` now enforces top-level/per-router
site_id agreement. A `security` parcel (rekey 172800, anti-replay 4096,
integrity none) was also added to the shared system profile and applied.

## Edge deployment system-profile requirements — 2026-07-27

After `CG-BXT` and `PG-BXT` were created successfully, edge deployment
validation reported that the system feature profile was missing Global and
OMP features. NaC 1.4.0 models these as direct `global:` and `omp:` mappings
under each `system_profiles[]` entry. The installed provider schema requires
only `name` and `feature_profile_id`; the module supplies the profile ID.

The shared system template now creates named Global and OMP parcels with no
optional overrides, preserving provider/vManage defaults until explicit
fabric requirements are confirmed. `validate_model.py` requires both parcels
for every system profile so this cannot regress.

---

## BGP service feature — redistribution + route-policy (2026-08-06)

Verified from `sdwan_features_service.tf` in nac-sdwan 1.4.0
(`sites/bxt/.terraform/modules/sdwan/sdwan_features_service.tf`, lines 1–210).

| Attribute | Key confirmed | Container | Notes |
|---|---|---|---|
| OMP redistribute | `ipv4_redistributes[].protocol: omp` | `bgp_features[]` directly | Key is `ipv4_redistributes`, NOT `redistribute` |
| connected redistribute | `ipv4_redistributes[].protocol: connected` | same | Same list entry |
| propagate_community | `propagate_community: true` | `bgp_features[]` directly | Confirmed line 206 |
| fall_over_bfd (neighbor) | NOT PRESENT | — | No `bfd`/`fall_over` field anywhere in neighbor block (lines 42–92); handle via CLI add-on |
| send_community (neighbor) | `send_community: both` | `ipv4_neighbors[]` | Confirmed line 83 |
| route_policy_out (neighbor) | `address_families[].route_policy_out` | nested in `ipv4_neighbors[].address_families[]` | Takes a **route policy name** (string), NOT a `_variable` — resolves to `sdwan_service_route_policy_feature` resource ID; CLI-defined route-maps (cli.yaml) are NOT accessible via this path |
| route_policy_in (neighbor) | `address_families[].route_policy_in` | same | Same constraints as above |

### Critical implications

- **`ipv4_redistributes`** (not `redistribute`): the plan and all templates must use this key.
- **`fall_over_bfd`** moves entirely to CLI add-on (Task 5): add `neighbor <IP> fall-over bfd` under the BGP VRF stanza in the CLI block.
- **Route-map neighbor linkage (DC hub)**: since the data model's `route_policy_in/out` resolves only NaC data model route policies (not CLI add-on route-maps), the BGP neighbor → route-map wiring must also go through CLI add-on when activated. The commented block in `templates/dc/service.yaml` is kept as a design marker but noted as "requires CLI add-on linkage."

### Correct YAML structure for bgp_features (branch sites)

```yaml
bgp_features:
  - name: "BGP-VPN10"
    as_number_variable: bgp_as_number
    router_id_variable: bgp_router_id
    propagate_community: true
    ipv4_redistributes:
      - protocol: omp
      - protocol: connected
    ipv4_neighbors:
      - address_variable: bgp_neighbor_corp
        remote_as_variable: bgp_neighbor_remote_as
        send_community: both
        # fall_over_bfd → add via CLI add-on: neighbor <IP> fall-over bfd
```

---

## Recommended next steps (original, for reference)

1. Rewrite `templates/` + `build_site_values_yaml()` to the validated
   structure (root `sdwan:` key, real container names, `_variable:`
   mechanism, config-group/router attach shape).
2. Update `globals.yaml` (drop `auth_fallback`, `disk_enabled`,
   `attach.pseudo_commit_timer`; rename ntp/logging inner keys; move DNS
   into transport/service usage).
3. Update the CLAUDE.md `pseudo_commit_timer` hard rule to its UX2
   equivalent (`configuration_group_deploy` per router).
4. Decide chassis-ID sourcing (required for any real deploy).
5. Then `terraform plan` against a lab vManage as the final proof.
