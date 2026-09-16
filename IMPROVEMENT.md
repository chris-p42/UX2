# Code Review — Open Improvement Points

Original review: 2026-07-23, covering `generate.py`, `csv_to_values.py`,
`templates/`, `values/`, `globals.yaml`, `root-template/`, and generated
output under `sites/`.

Cleaned up 2026-07-24: resolved items removed. For the record, the
following were fixed and are no longer listed (details in the file
history / session notes):
state-loss on regen (`rmtree` now wipes `data/` only), device variables
wired into transport/service parcels via `{{var}}` references,
placeholder scan with `--strict`, branch-a transport contradictions,
CORP/INFRA VRF model (confirmed fused in VPN 10; separate VNs exist only
in the SDA fabric), `pseudo_commit_timer` on every attach.

---

## Highest priority

### 1. Validate every key name against the real module schema — ✅ VALIDATED & REWRITTEN 2026-07-24

The nac-sdwan 1.4.0 module source was traced (`SCHEMA-VALIDATION.md`)
and the full rewrite applied: root `sdwan:` key, real container names
(`feature_profiles.system_profiles` etc.), no `parcels:` wrapper,
`<field>_variable:` device-variable mechanism, config-group/router
attach shape with `configuration_group_deploy` gates (replacing the
then-assumed nonexistent UX2 `pseudo_commit_timer`). Corrected by live
validation on 2026-07-27: `pseudo_commit_timer: 0` is required per router as
a config-group system variable, while `configuration_group_deploy` remains
the independent deploy gate. CLAUDE.md and validation rules are updated,
per-site policy-object profile removed (single global object only),
values files converted to address-only IPs (masks static in templates).

Verified offline: generation clean, all YAML parses,
`utils_yaml_merge` accepts the model (profile-split-across-files
merge-by-name confirmed empirically on utils 1.0.2), and
`validate_model.py` cross-checks names, by-name references, and
variable coverage per router — all passing. `terraform plan` reaches
provider authentication (needs a live vManage; that's the remaining
proof).

**Still open**: chassis IDs are placeholders (`CHASSIS_ID_*`) — real
serials required before any deploy; app-priority (QoS) profile
modelling; SNMPv3 views/groups/users; BGP `as_number` + outbound
route-policies (placeholders/TODO in service templates); final
`terraform plan` against a lab vManage.

---

## Important

### 2. The `--out values` guard is bypassable — ✅ FIXED 2026-07-24

`csv_to_values.py` now compares resolved paths
(`pathlib.Path(args.out).resolve() == _VALUES_DIR`) so `--out ./values`,
`--out values/`, and absolute paths are all caught.

### 3. `--site-code` with a multi-site CSV silently collapses sites — ✅ FIXED 2026-07-24

`csv_to_values.py` now errors out immediately if `--site-code` is given
and the CSV contains more than one distinct site-id.

### 4. `site_id` uniqueness is a stated hard rule but never enforced — ✅ FIXED 2026-07-24

`generate.py main()` now pre-loads all values files, checks every
`site_id` against a seen-set, and exits with a clear error naming both
conflicting files before generating anything.

### 5. Key-name drift between hand-authored and generated values — ✅ FIXED 2026-07-24

`RENAME_MAP` now emits `vpn512_ip`/`vpn512_gateway` (matching
`values/bel.yaml` and `templates/dc/transport.yaml`).  `vpn512_ifname`
has no CSV column (the interface name is the path key itself —
`/512/GigabitEthernet0/...`); a comment in `RENAME_MAP` explains it must
be set manually in the output file.

### 6. No explicit file encoding in `generate.py` — ✅ FIXED 2026-07-24

All `open`/`read_text`/`write_text` calls in `generate.py` now pass
`encoding="utf-8"` explicitly.

---

## Minor

- **`--site` matches the file stem, not `site_code`** as the help text
  claims. Harmless now that file stems and site codes coincide
  (`bel.yaml`/BEL, `bxt.yaml`/BXT), but either match against the loaded
  `site_code` or fix the help text.
- **Lock-file advice is contradicted by `.gitignore`**: `providers.tf`
  says to pin the provider via the committed lock file, but
  `.terraform.lock.hcl` is gitignored and `sites/` is regenerated. Since
  `sites/` is disposable, consider pinning the provider version in
  `root-template/providers.tf` itself.
- **`RENAME_MAP` many-to-one mappings** (five paths →
  `vpn0_default_route`): last-write-wins per row is fine while the values
  are identical, but if a device ever has differing prefixes, one
  silently disappears. Add a cheap assertion — warn when two mapped
  columns write different values to the same target key.
- **Comment loss on global-ref files**: files containing `__GLOBAL:` are
  re-dumped by PyYAML, stripping all comments (`sites/*/data/system.yaml`
  is comment-free). If generated output should stay readable,
  `ruamel.yaml` round-trips comments; otherwise note it as an accepted
  trade-off.
- **`requirements.txt` is unpinned** (`PyYAML>=6.0`). Pin at least a
  major bound for reproducibility.
- **No repo-level validation entry point.** A `--check` mode on
  `generate.py` (site_id uniqueness, placeholder scan already done, all
  `__GLOBAL:` keys resolvable, every `VARIANTS` file exists on disk)
  would make CI trivial later.
- **`branch-b` variant is unexercised**: with the placeholder sites
  parked in `DEMO/`, no site in `values/` uses
  `templates/branch/transport-b.yaml`. Its variable set is also an
  assumption (branch-a minus MPLS/TLOC-EXT) — verify against a real
  branch-b export when one exists.

---

## Suggested priority order

1. ~~Item 1 — schema validation~~ ✅
2. ~~Items 2–4 — guard-rail fixes~~ ✅
3. ~~Items 5–6 — RENAME_MAP alignment and explicit UTF-8 encoding~~ ✅
4. Minor list as opportunity allows; fold several of them into a
   `--check` mode.
