# BGP Redistribution + Route-Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire BGP↔OMP redistribution on all sites and add commented route-map CLI blocks (DC hub only) so policies can be activated by uncommenting without structural changes.

**Architecture:** Data model handles BGP structure (AS, router-id, neighbors, redistribution flags, per-neighbor attributes). Route-map blocks are raw IOS-XE CLI in the DC's existing CLI add-on profile (`dc/cli.yaml`) — always rendered, harmless until a neighbor references them. Neighbor→route-map linkage stays commented in `dc/service.yaml` until policies are ready to activate; the matching device variables stay commented in `bel.yaml` to avoid vManage rejecting unmatched device variables.

**Tech Stack:** Python 3 (generate.py), Terraform + netascode/nac-sdwan 1.4.0, Cisco SD-WAN vManage UX2 data model, YAML.

## Global Constraints

- Never edit files under `sites/` — generated output only; fix templates/values and regenerate.
- NaC module uses `<field>_variable: varname` (not `{{varname}}`); `{{...}}` sends a literal brace-string.
- Device variables submitted to vManage must match active feature parcel variables exactly. Commented-out `_variable:` keys in templates = not submitted = safe.
- DSCP values must be decimal integers, never PHB keywords.
- `__SITE__` token in templates is replaced with the site's `site_code` (uppercase) by generate.py.
- `__GLOBAL:<dotted.key>__` token is replaced with the value from `globals.yaml` (type-preserved).
- NaC module source is at `sites/bxt/.terraform/modules/sdwan/` (downloaded by `terraform init`).
- Key schema file: `sites/bxt/.terraform/modules/sdwan/sdwan_features_service.tf`.
- Run `python generate.py --site <code>` (lowercase site_code) to regenerate a single site.
- Verify generated output at `sites/<site>/data/`.
- Run `terraform validate` from inside `sites/<site>/` after regeneration.

---

### Task 1: Verify BGP data-model schema keys in NaC 1.4.0

**Files:**
- Read: `sites/bxt/.terraform/modules/sdwan/sdwan_features_service.tf`
- Update: `SCHEMA-VALIDATION.md` (append findings)

**Interfaces:**
- Produces: confirmed key names for Tasks 3 and 4. If a key is absent, that attribute moves to CLI add-on in Task 5.

- [ ] **Step 1: Open the NaC module BGP feature source**

```powershell
Select-String -Path "sites\bxt\.terraform\modules\sdwan\sdwan_features_service.tf" -Pattern "bgp|redistribute|propagate|bfd|send_community|route_policy" -Context 2
```

Look for the following — note the exact key name found (or "not present") for each:

| Attribute | What to search for | Expected key |
|---|---|---|
| OMP redistribution | `redistribute` near bgp context | `redistribute[].protocol` |
| Connected redistribution | same block | `redistribute[].protocol: connected` |
| Community propagation | `propagate` | `propagate_community` |
| BFD fall-over on neighbor | `bfd` near `ipv4_neighbors` | `fall_over_bfd` |
| Send-community on neighbor | `send_community` | `send_community` |
| Route-policy inbound on neighbor | `route_policy` near `ipv4_neighbors` | `route_policy_in` or `route_policy_in_variable` |
| Route-policy outbound on neighbor | same | `route_policy_out` or `route_policy_out_variable` |

- [ ] **Step 2: Cross-check with address_families wrapping**

Some NaC versions wrap redistribution inside an `address_families[]` block rather than directly on `bgp_features[]`. Search:

```powershell
Select-String -Path "sites\bxt\.terraform\modules\sdwan\sdwan_features_service.tf" -Pattern "address_famil" -Context 3
```

If `address_families[]` is the container for `redistribute`, the YAML must nest accordingly:
```yaml
bgp_features:
  - name: "BGP-VPN10"
    ...
    address_families:
      - family_type: ipv4-unicast
        redistribute:
          - protocol: omp
          - protocol: connected
        propagate_community: true
```
If redistribution is directly on `bgp_features[]`, no nesting is needed.

- [ ] **Step 3: Document findings**

Append a new section to `SCHEMA-VALIDATION.md`:

```markdown
## BGP service feature — redistribution + route-policy (2026-08-06)

Verified from `sdwan_features_service.tf` in nac-sdwan 1.4.0:

| Attribute | Key confirmed | Container |
|---|---|---|
| OMP redistribute | <FILL IN> | <bgp_features[] or address_families[]> |
| connected redistribute | <FILL IN> | same |
| propagate_community | <FILL IN or NOT PRESENT — use CLI add-on> | |
| fall_over_bfd (neighbor) | <FILL IN or NOT PRESENT> | ipv4_neighbors[] |
| send_community (neighbor) | <FILL IN or NOT PRESENT> | ipv4_neighbors[] |
| route_policy_out (neighbor) | <FILL IN or NOT PRESENT> | ipv4_neighbors[] |
| route_policy_in (neighbor) | <FILL IN or NOT PRESENT> | ipv4_neighbors[] |

Keys marked NOT PRESENT → handled in CLI add-on (Task 5).
```

- [ ] **Step 4: Commit findings**

```bash
git add SCHEMA-VALIDATION.md
git commit -m "docs: verify BGP redistribute/route-policy schema keys in NaC 1.4.0"
```

---

### Task 2: Flip `advertise_ipv4_bgp` in system template

**Files:**
- Modify: `templates/_shared/system.yaml` (line 84)

**Interfaces:**
- Produces: fabric-wide BGP→OMP redistribution; all sites pick this up on next generate.

- [ ] **Step 1: Make the change**

In `templates/_shared/system.yaml`, find the OMP parcel and change:
```yaml
          advertise_ipv4_bgp: false
```
to:
```yaml
          advertise_ipv4_bgp: true
```

- [ ] **Step 2: Regenerate all sites and verify**

```bash
python generate.py
```

Expected: no errors. Then inspect the OMP parcel in the generated output for one site:

```bash
python -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('sites/bxt/data/system.yaml').read_text())
omp = next(p['omp'] for p in d['sdwan']['feature_profiles']['system_profiles'] if 'omp' in p)
print('advertise_ipv4_bgp:', omp.get('advertise_ipv4_bgp'))
"
```

Expected output: `advertise_ipv4_bgp: True`

- [ ] **Step 3: Run terraform validate on BXT**

```powershell
Set-Location sites\bxt; terraform validate; Set-Location ..\..
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add templates/_shared/system.yaml
git commit -m "feat: enable advertise_ipv4_bgp on OMP parcel (BGP->OMP redistribution, all sites)"
```

---

### Task 3: Branch service templates — redistribution + per-neighbor attributes

**Files:**
- Modify: `templates/branch/service.yaml`
- Modify: `templates/branch/service-routed.yaml`

**Interfaces:**
- Consumes: exact key names from Task 1 (adjust if Task 1 found different names or NOT PRESENT).
- Produces: branch BGP features with OMP+connected redistribution and per-neighbor BFD/send-community.

**Note:** If Task 1 found that a key is NOT PRESENT in the NaC module, skip it here — it will be handled in Task 5's CLI add-on block instead. The structure below assumes all keys exist; adjust key names to match Task 1 findings exactly.

- [ ] **Step 1: Update `templates/branch/service.yaml` bgp_features block**

Find the existing `bgp_features` block (currently has `as_number_variable`, `router_id_variable`, `ipv4_neighbors`). Replace it with:

```yaml
        bgp_features:
          - name: "BGP-VPN10"
            as_number_variable: bgp_as_number
            router_id_variable: bgp_router_id
            redistribute:
              - protocol: omp
              - protocol: connected
            propagate_community: true
            ipv4_neighbors:
              - address_variable: bgp_neighbor_corp
                remote_as_variable: bgp_neighbor_remote_as
                fall_over_bfd: true
                send_community: both
              - address_variable: bgp_neighbor_infra
                remote_as_variable: bgp_neighbor_remote_as
                fall_over_bfd: true
                send_community: both
```

If Task 1 found that `redistribute` nests under `address_families[]`, use this structure instead:
```yaml
        bgp_features:
          - name: "BGP-VPN10"
            as_number_variable: bgp_as_number
            router_id_variable: bgp_router_id
            address_families:
              - family_type: ipv4-unicast
                redistribute:
                  - protocol: omp
                  - protocol: connected
                propagate_community: true
            ipv4_neighbors:
              - address_variable: bgp_neighbor_corp
                remote_as_variable: bgp_neighbor_remote_as
                fall_over_bfd: true
                send_community: both
              - address_variable: bgp_neighbor_infra
                remote_as_variable: bgp_neighbor_remote_as
                fall_over_bfd: true
                send_community: both
```

- [ ] **Step 2: Apply the identical change to `templates/branch/service-routed.yaml`**

The `bgp_features` block in `service-routed.yaml` is structurally identical to `service.yaml`. Apply the exact same replacement (same keys, same structure).

- [ ] **Step 3: Regenerate BXT and CML**

```bash
python generate.py --site bxt
python generate.py --site cml
```

Expected: no errors.

- [ ] **Step 4: Inspect the generated BGP feature for BXT**

```bash
python -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('sites/bxt/data/service.yaml').read_text())
bgp = d['sdwan']['feature_profiles']['service_profiles'][0]['bgp_features'][0]
import json; print(json.dumps(bgp, indent=2))
"
```

Expected: output shows `redistribute` list with `omp` and `connected`, `propagate_community: true`, and each neighbor has `fall_over_bfd: true` and `send_community: both`.

- [ ] **Step 5: Terraform validate**

```powershell
Set-Location sites\bxt; terraform validate; Set-Location ..\..
Set-Location sites\cml;  terraform validate; Set-Location ..\..
```

Expected: `Success!` on both.

- [ ] **Step 6: Commit**

```bash
git add templates/branch/service.yaml templates/branch/service-routed.yaml
git commit -m "feat: add OMP+connected redistribution and BFD/send-community to branch BGP features"
```

---

### Task 4: DC service template — redistribution + commented route-policy linkage

**Files:**
- Modify: `templates/dc/service.yaml`

**Interfaces:**
- Consumes: exact key names from Task 1.
- Produces: DC BGP feature with redistribution; commented neighbor→route-map linkage that can be activated by uncommenting two lines.

**Why commented:** vManage rejects device variable submissions containing variables not referenced by any active feature parcel. If `route_policy_out_variable: bgp_policy_out` is a YAML comment (`#`), the NaC module never generates that field → vManage never expects `bgp_policy_out` in device variables → no rejection.

- [ ] **Step 1: Update `templates/dc/service.yaml` bgp_features block**

Find the existing `bgp_features` block. Replace with (use same `address_families` nesting as Task 3 if that was required):

```yaml
        bgp_features:
          - name: "BGP-VPN10"
            as_number_variable: bgp_as_number
            router_id_variable: bgp_router_id
            redistribute:
              - protocol: omp
              - protocol: connected
            propagate_community: true
            ipv4_neighbors:
              - address_variable: bgp_neighbor_core
                remote_as_variable: bgp_neighbor_remote_as
                fall_over_bfd: true
                send_community: both
                # To activate route-policy: uncomment the two lines below,
                # fill in bgp_policy_in / bgp_policy_out in values/bel.yaml,
                # and replace PLACEHOLDER values in templates/dc/cli.yaml.
                # route_policy_in_variable: bgp_policy_in
                # route_policy_out_variable: bgp_policy_out
```

- [ ] **Step 2: Regenerate BEL and inspect**

```bash
python generate.py --site bel
```

Expected: no errors, no unexpected placeholder warnings (the route-policy variables are YAML comments, never parsed).

Inspect the generated DC BGP feature:
```bash
python -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('sites/bel/data/service.yaml').read_text())
bgp = d['sdwan']['feature_profiles']['service_profiles'][0]['bgp_features'][0]
import json; print(json.dumps(bgp, indent=2))
"
```

Expected: `redistribute` present, `propagate_community: true`, core neighbor has `fall_over_bfd` and `send_community`. No `route_policy_in` or `route_policy_out` fields (they are YAML comments).

- [ ] **Step 3: Terraform validate**

```powershell
Set-Location sites\bel; terraform validate; Set-Location ..\..
```

Expected: `Success!`

- [ ] **Step 4: Commit**

```bash
git add templates/dc/service.yaml
git commit -m "feat: add redistribution + commented route-policy linkage to DC BGP feature"
```

---

### Task 5: DC CLI add-on — route-map blocks with PLACEHOLDER values

**Files:**
- Modify: `templates/dc/cli.yaml`

**Interfaces:**
- Produces: two named route-map blocks (`RT-POL-IN-BEL` and `RT-POL-OUT-BEL`) in the DC's CLI add-on profile. Route-maps are present and rendered but have no effect until a BGP neighbor references them (Task 4's commented lines are activated).

**Key constraints:**
- `__SITE__` token in the `cli_configuration` string is replaced by generate.py with the site's `site_code` (`BEL`).
- No `{{variable}}` syntax — the NaC module treats `{{...}}` as a literal brace-string (SCHEMA-VALIDATION.md §1.4). Values are either hardcoded or use `__SITE__`.
- PLACEHOLDER values (ALL_CAPS) generate.py warnings are expected and intentional — they block accidental deploy until real values are filled in.
- Route-map blocks are always rendered; they are harmless without neighbor reference.

- [ ] **Step 1: Append route-map CLI to `templates/dc/cli.yaml`**

The current file has a `cli_configuration` YAML literal block (`|`). Extend it by appending the route-map section. The full updated `cli_configuration` value should be:

```yaml
sdwan:
  feature_profiles:
    cli_profiles:
      - name: "CLI-BEL"
        description: "CLI add-on - BEL (campus port-channel + BGP route-policy)"
        config:
          name: "CLI-CONFIG-BEL"
          cli_configuration: |
            interface Port-channel1
             description CAMPUS-LAG
             no shutdown
            !
            ! BGP route-policy — activate by:
            !   1. replacing PLACEHOLDER values below with real values
            !   2. uncommenting route_policy_in/out_variable in templates/dc/service.yaml
            !   3. uncommenting bgp_policy_in/out in values/bel.yaml (both routers)
            !
            route-map RT-POL-IN-__SITE__ permit 10
             match ip address prefix-list BGP_POLICY_IN_PFX_PLACEHOLDER
             set local-preference BGP_POLICY_IN_LOCALPREF_PLACEHOLDER
            route-map RT-POL-IN-__SITE__ deny 65535
            !
            route-map RT-POL-OUT-__SITE__ permit 10
             match ip address prefix-list BGP_POLICY_OUT_PFX_SPECIFIC_PLACEHOLDER
             set metric BGP_POLICY_OUT_MED_PLACEHOLDER
             set as-path prepend BGP_POLICY_OUT_ASPREPEND_PLACEHOLDER
            route-map RT-POL-OUT-__SITE__ permit 20
             set metric BGP_POLICY_OUT_MED_PLACEHOLDER
            route-map RT-POL-OUT-__SITE__ deny 65535
```

- [ ] **Step 2: Regenerate BEL and verify __SITE__ substitution**

```bash
python generate.py --site bel
```

Expected output from generate.py: placeholder warnings for `BGP_POLICY_*` values (expected and intentional — do not fix them).

Inspect the generated CLI configuration:
```bash
python -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('sites/bel/data/cli.yaml').read_text())
cli = d['sdwan']['feature_profiles']['cli_profiles'][0]['config']['cli_configuration']
print(cli)
"
```

Expected: the string contains `RT-POL-IN-BEL` and `RT-POL-OUT-BEL` (not `__SITE__`), and the PLACEHOLDER strings are present literally.

- [ ] **Step 3: Terraform validate**

```powershell
Set-Location sites\bel; terraform validate; Set-Location ..\..
```

Expected: `Success!`

- [ ] **Step 4: Commit**

```bash
git add templates/dc/cli.yaml
git commit -m "feat: add commented route-map blocks to DC CLI add-on (RT-POL-IN/OUT-BEL, PLACEHOLDER values)"
```

---

### Task 6: bel.yaml — commented route-policy activation block

**Files:**
- Modify: `values/bel.yaml`

**Interfaces:**
- Produces: commented variable block in both routers' sections. Activating = uncomment + fill in values + uncomment service.yaml lines (Task 4).

**Why both routers:** Each router's `device_variables` block is independent. Both routers peer with the DC core and both need the route-policy variables once activated.

- [ ] **Step 1: Add commented block to router1 section in `values/bel.yaml`**

Find the end of router1's BGP section (after `bgp_neighbor_remote_as`). Add the following block immediately after:

```yaml
    # ── BGP route-policy (commented — activate per spec/2026-08-06-bgp-redistribution-routepolicy-design.md)
    # bgp_policy_in: RT-POL-IN-BEL             # must match route-map name in templates/dc/cli.yaml
    # bgp_policy_out: RT-POL-OUT-BEL           # must match route-map name in templates/dc/cli.yaml
```

- [ ] **Step 2: Add identical commented block to router2 section**

Find the end of router2's BGP section (after `bgp_neighbor_remote_as`). Add the same block:

```yaml
    # ── BGP route-policy (commented — activate per spec/2026-08-06-bgp-redistribution-routepolicy-design.md)
    # bgp_policy_in: RT-POL-IN-BEL             # must match route-map name in templates/dc/cli.yaml
    # bgp_policy_out: RT-POL-OUT-BEL           # must match route-map name in templates/dc/cli.yaml
```

- [ ] **Step 3: Regenerate BEL and verify no new warnings**

```bash
python generate.py --site bel
```

Expected: same placeholder warnings as Task 5 (BGP_POLICY_* in cli.yaml), nothing new. The YAML-commented lines in bel.yaml are not parsed → no new device variables → no new vManage submission.

- [ ] **Step 4: Commit**

```bash
git add values/bel.yaml
git commit -m "docs: add commented BGP route-policy activation block to bel.yaml (both routers)"
```

---

### Task 7: Full validation and log update

**Files:**
- Read/validate: `sites/bxt/`, `sites/cml/`, `sites/bel/`
- Update: `claude_update.log`

- [ ] **Step 1: Full regeneration**

```bash
python generate.py
```

Expected: completes without errors. Placeholder warnings for BEL (BGP_POLICY_*, CHASSIS_ID_*, ROUTER_ID_*, GPS_*, BGP_AS_NUMBER, BGP_REMOTE_AS, BGP_CORE_NEIGHBOR_*) are expected.

- [ ] **Step 2: Terraform validate all active sites**

```powershell
Set-Location sites\bxt; terraform validate; Set-Location ..\..
Set-Location sites\cml; terraform validate; Set-Location ..\..
Set-Location sites\bel; terraform validate; Set-Location ..\..
```

Expected: `Success!` on all three.

- [ ] **Step 3: Spot-check OMP flag on all generated sites**

```bash
python -c "
import yaml, pathlib
for site in ['bxt', 'cml', 'bel']:
    d = yaml.safe_load(pathlib.Path(f'sites/{site}/data/system.yaml').read_text())
    profs = d['sdwan']['feature_profiles']['system_profiles']
    omp = next((p.get('omp',{}) for p in profs if 'omp' in p), {})
    print(f'{site}: advertise_ipv4_bgp =', omp.get('advertise_ipv4_bgp'))
"
```

Expected:
```
bxt: advertise_ipv4_bgp = True
cml: advertise_ipv4_bgp = True
bel: advertise_ipv4_bgp = True
```

- [ ] **Step 4: Spot-check branch BGP redistribution**

```bash
python -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('sites/bxt/data/service.yaml').read_text())
bgp = d['sdwan']['feature_profiles']['service_profiles'][0]['bgp_features'][0]
print('redistribute:', bgp.get('redistribute', bgp.get('address_families', [{}])[0].get('redistribute')))
print('propagate_community:', bgp.get('propagate_community', bgp.get('address_families', [{}])[0].get('propagate_community')))
"
```

Expected: `redistribute` shows `[{protocol: omp}, {protocol: connected}]`, `propagate_community: True`.

- [ ] **Step 5: Spot-check DC CLI route-maps rendered with BEL site code**

```bash
python -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('sites/bel/data/cli.yaml').read_text())
cli = d['sdwan']['feature_profiles']['cli_profiles'][0]['config']['cli_configuration']
assert 'RT-POL-IN-BEL' in cli, 'FAIL: __SITE__ not substituted'
assert '__SITE__' not in cli, 'FAIL: __SITE__ token not replaced'
print('PASS: route-map names correctly resolved to BEL')
"
```

Expected: `PASS: route-map names correctly resolved to BEL`

- [ ] **Step 6: Update claude_update.log**

Append to `claude_update.log`:

```
2026-08-06  MODIFY  templates/_shared/system.yaml  — advertise_ipv4_bgp: false → true (BGP→OMP redistribution, all sites)
2026-08-06  MODIFY  templates/branch/service.yaml  — added redistribute omp+connected, propagate_community, fall_over_bfd + send_community per neighbor
2026-08-06  MODIFY  templates/branch/service-routed.yaml  — same BGP changes as service.yaml (branch-a-routed / branch-b-routed variants)
2026-08-06  MODIFY  templates/dc/service.yaml  — added redistribute omp+connected, propagate_community, fall_over_bfd + send_community; commented route_policy_in/out_variable on core neighbor
2026-08-06  MODIFY  templates/dc/cli.yaml  — appended RT-POL-IN-BEL / RT-POL-OUT-BEL route-map blocks with PLACEHOLDER values
2026-08-06  MODIFY  values/bel.yaml  — added commented BGP route-policy activation block (both routers)
2026-08-06  MODIFY  SCHEMA-VALIDATION.md  — added BGP redistribute/route-policy schema findings (Task 1)
```

- [ ] **Step 7: Final commit**

```bash
git add claude_update.log
git commit -m "docs: update log for BGP redistribution + route-policy implementation"
```

---

## Activation guide (not part of this plan — for future reference)

When ready to activate route-maps on BEL:

1. In `templates/dc/cli.yaml`: replace all `PLACEHOLDER` strings with real values (prefix-list names, MED, AS-path prepend string).
2. In `templates/dc/service.yaml`: uncomment the two lines:
   ```yaml
   route_policy_in_variable: bgp_policy_in
   route_policy_out_variable: bgp_policy_out
   ```
3. In `values/bel.yaml` (both routers): uncomment and confirm:
   ```yaml
   bgp_policy_in: RT-POL-IN-BEL
   bgp_policy_out: RT-POL-OUT-BEL
   ```
4. Run `python generate.py --site bel` → `terraform plan` → review → `terraform apply` (with explicit approval).
