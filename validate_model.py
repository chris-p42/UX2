"""Ad-hoc cross-check of rendered sites/<site>/data/ against module expectations.

Checks (mirroring nac-sdwan 1.4.0 for_each logic and variable resolution):
  1. every profile / interface / lan_vpn / feature entry has a static `name`
  2. every by-name reference resolves (config group -> profiles,
     lan_vpn.bgp/ospf -> *_features, svi dhcp_server -> dhcp_servers,
     router configuration_group/policy_group -> declared groups)
  3. every `<field>_variable: <var>` in the profiles has a matching key in
     EVERY router's device_variables for that site (catches typos)
  4. module/provider constraints that JSON schema validation cannot catch:
      BGP uses `ipv4_neighbors`, variable-address Ethernet interfaces declare
      `ipv4_address_type: static`, required config-group system variables are
      present, and router variables contain no unknown keys
  5. neighbor address_families[].route_policy_out/_in resolve to a
     route_policies[] entry of the SAME service profile
  6. route_policies[] prefix-list matches resolve to an ipv4_prefix_lists[]
     entry of THIS site's policy_object_profile, and a config group only
     attaches a policy_object_profile the site actually declares

Checks 5 and 6 exist because the module resolves those references through
try(): a typo yields no terraform error, just a silently missing route-map or
a match that quietly matches everything.
"""
import glob
import re
import pathlib
import sys

import yaml


REPO_ROOT = pathlib.Path(__file__).resolve().parent
SITES_GLOB = str(REPO_ROOT / "sites" / "*")
IMPLICIT_DEVICE_VARIABLES = {"host_name", "system_ip", "site_id"}
REQUIRED_SYSTEM_DEVICE_VARIABLES = {"pseudo_commit_timer"}

# vManage parcel-name limit — see check 7 for how this was established.
PARCEL_NAME_MAX = 32
# Longest name that still tolerates a site code one character longer than
# today's three-letter ones.
PARCEL_NAME_SAFE = 31


def deep_merge(a, b):
    """Mimic utils_yaml_merge: dicts merge recursively; lists of dicts merge
    by `name` when both sides have an item with the same name, else append."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = deep_merge(out[k], v) if k in out else v
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = list(a)
        for item in b:
            if isinstance(item, dict) and "name" in item:
                for i, existing in enumerate(out):
                    if isinstance(existing, dict) and existing.get("name") == item["name"]:
                        out[i] = deep_merge(existing, item)
                        break
                else:
                    out.append(item)
            else:
                out.append(item)
        return out
    return b


CLI_VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def collect_variables(node, acc):
    """Collect every device variable a feature profile actually references.

    Two syntaxes, both real:
      1. `<field>_variable: <name>` on a parcel field — the NaC data model form.
      2. `{{name}}` inside a CLI add-on body — templates/branch/cli.yaml pushes
         `router bgp {{cli_bgp_as}}` and friends this way.

    Form 2 was missed until 2026-09-04, which made this check report every
    cli_* variable as unreferenced on BXT and CML — five false positives per
    site, carried as "pre-existing failures" for weeks.  vManage never
    complained about them precisely because the CLI parcel does declare them.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if k.endswith("_variable") and isinstance(v, str):
                acc.add(v)
            else:
                collect_variables(v, acc)
    elif isinstance(node, list):
        for v in node:
            collect_variables(v, acc)
    elif isinstance(node, str):
        acc.update(CLI_VARIABLE_RE.findall(node))


errors = []
warnings = []
checked_sites = sorted(glob.glob(SITES_GLOB))
for site_dir in checked_sites:
    site = pathlib.Path(site_dir).name
    model = {}
    for f in glob.glob(site_dir + r"\data\*.yaml"):
        with open(f, encoding="utf-8") as fh:
            model = deep_merge(model, yaml.safe_load(fh) or {})
    sdwan = model.get("sdwan", {})
    fps = sdwan.get("feature_profiles", {})

    def err(msg):
        errors.append(f"{site}: {msg}")

    # 1. name presence on keyed entries
    for ptype in ("system_profiles", "transport_profiles", "service_profiles", "cli_profiles"):
        for p in fps.get(ptype, []):
            if "name" not in p:
                err(f"{ptype} entry missing name")
            if ptype == "system_profiles":
                for mandatory_parcel in ("global", "omp"):
                    if not isinstance(p.get(mandatory_parcel), dict):
                        err(
                            f"system profile {p.get('name')} missing mandatory "
                            f"{mandatory_parcel} parcel"
                        )
                # NaC 1.4.0 consumes `integrity_types` (plural, list); a
                # singular `integrity_type` key is silently ignored — the
                # exact trap that shipped an unset integrity to vManage
                # (found 2026-07-29).
                if isinstance(p.get("security"), dict):
                    sec = p["security"]
                    if "integrity_type" in sec:
                        err(
                            f"system profile {p.get('name')} security uses unsupported "
                            "'integrity_type'; nac-sdwan 1.4.0 expects 'integrity_types' (list)"
                        )
                    # A null integrityType breaks vManage device config
                    # generation at deploy (security.vt NPE, hit live
                    # 2026-07-29) — the parcel must always pin the list.
                    if not isinstance(sec.get("integrity_types"), list) or not sec["integrity_types"]:
                        err(
                            f"system profile {p.get('name')} security must set "
                            "non-empty 'integrity_types' (vManage deploy fails on a "
                            "null integrityType; GUI default is [esp, ip-udp-esp])"
                        )
            for vpn_key in ("wan_vpn", "management_vpn"):
                vpn = p.get(vpn_key) or {}
                for i in vpn.get("ethernet_interfaces", []):
                    if "name" not in i:
                        err(f"{p.get('name')}/{vpn_key} interface missing static name")
            for lv in p.get("lan_vpns", []):
                if "name" not in lv:
                    err(f"{p.get('name')} lan_vpn missing name")
                for ikey in ("ethernet_interfaces", "svi_interfaces"):
                    for i in lv.get(ikey, []):
                        if "name" not in i:
                            err(f"{p.get('name')}/{lv.get('name')} {ikey} entry missing static name")

    # Policy objects live in ONE profile per terraform root (nac4 = one root
    # per site).  sdwan_features_service.tf:2037 resolves a prefix-list match
    # against the policy-object resource of the CURRENT root, so anything
    # declared elsewhere resolves to null.
    policy_objects = fps.get("policy_object_profile") or {}
    ipv4_prefix_list_names = {
        pl["name"] for pl in policy_objects.get("ipv4_prefix_lists", []) if "name" in pl
    }

    # 2. by-name references
    svc_profiles = fps.get("service_profiles", [])
    for p in svc_profiles:
        for bgp in p.get("bgp_features", []):
            if "neighbors" in bgp:
                err(
                    f"bgp feature {bgp.get('name')} uses unsupported 'neighbors'; "
                    "nac-sdwan 1.4.0 expects 'ipv4_neighbors'"
                )
            for index, neighbor in enumerate(bgp.get("ipv4_neighbors", [])):
                if "remote_as" not in neighbor and "remote_as_variable" not in neighbor:
                    err(
                        f"bgp feature {bgp.get('name')} ipv4_neighbors[{index}] "
                        "requires remote_as or remote_as_variable"
                    )
        # 5. route-map references (added 2026-08-18).  The module wraps every
        # one of these in try(), so a typo produces NO terraform error at all:
        # out_route_policy_id silently becomes null and the route-map is never
        # applied to the neighbor.  This check is the only thing that catches it
        # before the config reaches a device.
        route_policy_names = {
            rp["name"] for rp in p.get("route_policies", []) if "name" in rp
        }
        for bgp in p.get("bgp_features", []):
            for index, neighbor in enumerate(bgp.get("ipv4_neighbors", [])):
                for af in neighbor.get("address_families", []):
                    for ref_key in ("route_policy_out", "route_policy_in"):
                        ref = af.get(ref_key)
                        if ref is not None and ref not in route_policy_names:
                            err(
                                f"bgp feature {bgp.get('name')} ipv4_neighbors[{index}] "
                                f"{ref_key} references unknown route_policy '{ref}' "
                                f"in service profile {p.get('name')}"
                            )

        # 6. route-map prefix-list matches must resolve inside the SAME root —
        # same silent-try() failure mode, except here the route-map still gets
        # applied, just without its match: a permit sequence that matches
        # everything instead of the intended prefixes.
        for rp in p.get("route_policies", []):
            for seq in rp.get("sequences", []):
                ref = (seq.get("match_entries") or {}).get("ipv4_address_prefix_list")
                if ref is not None and ref not in ipv4_prefix_list_names:
                    err(
                        f"route_policy {rp.get('name')} sequence {seq.get('id')} "
                        f"matches unknown ipv4 prefix-list '{ref}' — it must be "
                        "declared in this site's policy_object_profile "
                        "(templates/branch/policy-objects.yaml), not in another "
                        "terraform root"
                    )

        bgp_names = {b["name"] for b in p.get("bgp_features", [])}
        ospf_names = {o["name"] for o in p.get("ospf_features", [])}
        dhcp_names = {d["name"] for d in p.get("dhcp_servers", [])}
        for lv in p.get("lan_vpns", []):
            if "bgp" in lv and lv["bgp"] not in bgp_names:
                err(f"lan_vpn {lv['name']} references unknown bgp {lv['bgp']}")
            if "ospf" in lv and lv["ospf"] not in ospf_names:
                err(f"lan_vpn {lv['name']} references unknown ospf {lv['ospf']}")
            for i in lv.get("svi_interfaces", []):
                if "dhcp_server" in i and i["dhcp_server"] not in dhcp_names:
                    err(f"svi {i['name']} references unknown dhcp_server {i['dhcp_server']}")
    for p in fps.get("transport_profiles", []):
        ospf_names = {o["name"] for o in p.get("ospf_features", [])}
        wan = p.get("wan_vpn") or {}
        if "ospf" in wan and wan["ospf"] not in ospf_names:
            err(f"wan_vpn references unknown ospf {wan['ospf']}")

    # Provider constraint: an Ethernet IPv4 address variable is conditional
    # on ipv4_address_type being explicitly set to static.
    for ptype in ("transport_profiles", "service_profiles"):
        for p in fps.get(ptype, []):
            interface_groups = []
            for vpn_key in ("wan_vpn", "management_vpn"):
                vpn = p.get(vpn_key) or {}
                interface_groups.append((vpn_key, vpn.get("ethernet_interfaces", [])))
            for lan_vpn in p.get("lan_vpns", []):
                interface_groups.append(
                    (f"lan_vpn {lan_vpn.get('name')}", lan_vpn.get("ethernet_interfaces", []))
                )
            for group_name, interfaces in interface_groups:
                for interface in interfaces:
                    if (
                        "ipv4_address_variable" in interface
                        and interface.get("ipv4_address_type") != "static"
                    ):
                        err(
                            f"{p.get('name')}/{group_name}/{interface.get('name')}: "
                            "ipv4_address_variable requires ipv4_address_type: static"
                        )
                    # Tunnel allow-services: NaC 1.4.0 only consumes flat
                    # `allow_service_<svc>` keys under tunnel_interface; the
                    # nested map spellings below were silently ignored for
                    # months (found 2026-07-29) — reject them outright.
                    tunnel = interface.get("tunnel_interface")
                    if isinstance(tunnel, dict):
                        for bad_key in ("allow_services", "allowed_protocols"):
                            if bad_key in tunnel:
                                err(
                                    f"{p.get('name')}/{group_name}/{interface.get('name')}: "
                                    f"tunnel_interface uses unsupported '{bad_key}'; "
                                    "use flat allow_service_<svc> keys (e.g. allow_service_https)"
                                )

    profile_names = {
        ptype: {p["name"] for p in fps.get(ptype, [])}
        for ptype in ("system_profiles", "transport_profiles", "service_profiles", "cli_profiles")
    }
    cg_names, pg_names = set(), set()
    for cg in sdwan.get("configuration_groups", []):
        cg_names.add(cg["name"])
        for ref_key, ptype in (
            ("system_profile", "system_profiles"),
            ("transport_profile", "transport_profiles"),
            ("service_profile", "service_profiles"),
            ("cli_profile", "cli_profiles"),
        ):
            if ref_key in cg and cg[ref_key] not in profile_names[ptype]:
                err(f"config group {cg['name']} references unknown {ref_key} {cg[ref_key]}")
        # policy_object_profile is a single object, not a list — and attaching
        # it when this root declares none makes sdwan_configuration_groups.tf:10
        # index policy_object_feature_profile[0] on a count = 0 resource.
        if "policy_object_profile" in cg:
            declared = policy_objects.get("name")
            if cg["policy_object_profile"] != declared:
                err(
                    f"config group {cg['name']} references policy_object_profile "
                    f"'{cg['policy_object_profile']}' but this site declares "
                    f"'{declared}' — the profile must exist in the SAME terraform root"
                )
    for pg in sdwan.get("policy_groups", []):
        pg_names.add(pg["name"])

    # 3. variable references vs device_variables, and router group refs
    referenced = set()
    collect_variables(fps, referenced)
    for s in sdwan.get("sites", []):
        for r in s.get("routers", []):
            if r.get("configuration_group") not in cg_names:
                err(f"router {r.get('chassis_id')} references unknown config group")
            if r.get("policy_group") not in pg_names:
                err(f"router {r.get('chassis_id')} references unknown policy group")
            dv = set((r.get("device_variables") or {}).keys())
            missing = referenced - dv
            if missing:
                err(f"router {r.get('chassis_id')}: device_variables missing {sorted(missing)}")
            missing_system = REQUIRED_SYSTEM_DEVICE_VARIABLES - dv
            if missing_system:
                err(
                    f"router {r.get('chassis_id')}: required config-group system "
                    f"device_variables missing {sorted(missing_system)}"
                )
            unknown = (
                dv
                - referenced
                - IMPLICIT_DEVICE_VARIABLES
                - REQUIRED_SYSTEM_DEVICE_VARIABLES
            )
            if unknown:
                err(
                    f"router {r.get('chassis_id')}: device_variables not referenced "
                    f"by active feature profiles {sorted(unknown)}"
                )

    # 7. Parcel name length.
    #
    # vManage rejects an over-long parcel name at APPLY time, never at plan:
    #   HTTP 400 SCHVALID0001
    #   {"Validation Errors":{"Invalid Format Attributes":["name"]}}
    # The message names the field but not the rule, so it is worth catching here.
    #
    # LIMIT ESTABLISHED 2026-09-04 on a live apply against sites/bxt: the two
    # application lists at 34 characters (LO_Business_Network_Control_V2-BXT,
    # LO_Business_MM_Conferencing_V2-BXT) were rejected while every name at 31
    # or below was created without complaint.  That brackets the limit to
    # 31 < limit <= 33; 32 is the value Cisco documents for parcel names.
    #
    # BUDGET: the name carries a -<SITE> suffix, so the base written in
    # templates/ has 32 - 1 - len(site_code) characters, i.e. 28 for a 3-letter
    # site code and 27 for a 4-letter one.  Names between 29 and 32 therefore
    # pass today but would break when a longer site code is onboarded — they are
    # reported as a warning rather than a failure.
    for group, items in (
        ("policy_object_profile", [fps.get("policy_object_profile", {})]),
        ("application_priority_profiles", fps.get("application_priority_profiles", [])),
    ):
        for prof in items:
            if not isinstance(prof, dict):
                continue
            named = [(prof.get("name"), group)]
            for sub, label in (
                ("application_lists", "application_list"),
                ("sla_classes", "sla_class"),
                ("forwarding_classes", "forwarding_class"),
                ("ipv4_data_prefix_lists", "ipv4_data_prefix_list"),
                ("ipv4_prefix_lists", "ipv4_prefix_list"),
                ("qos_policies", "qos_policy"),
                ("traffic_policies", "traffic_policy"),
            ):
                named += [(o.get("name"), label) for o in prof.get(sub, []) or []]
            for name, label in named:
                if not name:
                    continue
                if len(name) > PARCEL_NAME_MAX:
                    err(
                        f"{label} name '{name}' is {len(name)} characters, over the "
                        f"{PARCEL_NAME_MAX}-character vManage parcel-name limit — "
                        f"the apply will fail with SCHVALID0001 'Invalid Format "
                        f"Attributes: name'"
                    )
                elif len(name) > PARCEL_NAME_SAFE:
                    warnings.append(
                        f"{site}: {label} name '{name}' is {len(name)} characters — "
                        f"under the {PARCEL_NAME_MAX} limit today, but leaves no room "
                        f"for a site code longer than the current one"
                    )


# 8. Keys the module never reads (warning only).
#
# nac-sdwan resolves every optional key through try(), so a key we invented or
# mistyped does not fail — it is silently dropped and the feature quietly does
# not exist.  Two live incidents came from exactly this:
#   2026-09-02  application_lists used `entries:`; the module reads
#               `applications:`, so the list would have been created EMPTY.
#   2026-09-04  the OSPF MD5 block used `message_digest_keys/id/algorithm/
#               key_variable`; the module reads flat
#               `authentication_message_digest_key_id/_variable`, so no variable
#               was declared and the config-group PUT was rejected with
#               SCHVALID0001 "Not Defined In Schema Attributes".
#
# This check greps the module source for every identifier appearing after a dot
# and reports any key in sites/<site>/data/ that never appears there.  It is
# deliberately over-permissive (an identifier used anywhere in the module counts
# as known), so it produces few false positives and catches invented keys.
# It is a WARNING, not a failure: the module source is only present after
# `terraform init`, and the heuristic cannot prove a key is wrong.
MODULE_TF = sorted(glob.glob(str(REPO_ROOT / "sites" / "*" / ".terraform" / "modules" / "sdwan" / "*.tf")))
if MODULE_TF:
    module_text = "".join(pathlib.Path(f).read_text(encoding="utf-8", errors="ignore") for f in MODULE_TF)
    known_keys = set(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", module_text))

    # device_variables is a free-form name->value map (the names are ours, not
    # the module's schema), so its KEYS must not be checked against the module.
    # Same for the qos_dscp-style value maps: only structural keys matter here.
    OPAQUE_KEY_MAPS = {"device_variables"}

    def walk_keys(node, acc):
        if isinstance(node, dict):
            for k, v in node.items():
                acc.add(k)
                if k in OPAQUE_KEY_MAPS:
                    continue
                walk_keys(v, acc)
        elif isinstance(node, list):
            for v in node:
                walk_keys(v, acc)

    for site_dir in checked_sites:
        site = pathlib.Path(site_dir).name
        used = set()
        for f in sorted(glob.glob(str(pathlib.Path(site_dir) / "data" / "*.yaml"))):
            with open(f, encoding="utf-8") as fh:
                walk_keys(yaml.safe_load(fh) or {}, used)
        unknown = sorted(k for k in used if k not in known_keys)
        for k in unknown:
            warnings.append(
                f"{site}: key '{k}' appears in data/ but nowhere in the "
                f"nac-sdwan module source — it will be silently ignored by "
                f"try() and the feature it configures will not exist"
            )
else:
    warnings.append(
        "module source not found under sites/*/.terraform/modules/sdwan/ — "
        "check 8 (unknown keys) skipped; run `terraform init` in a site root "
        "to enable it"
    )

# 9. A named item split across files must not carry CONTRADICTORY scalars.
#
# This repo deliberately assembles one profile from several YAML files (see the
# SPLIT ACROSS FILES note in templates/_shared/policy-objects-common.yaml).  The
# merge pairs list items by `name`, but only while their scalar keys agree: give
# the same `name` two different `description` values and the merge keeps them as
# TWO items, after which the module's for_each aborts the plan with
#   "Two different items produced the key ..."  (sdwan_feature_profiles.tf:8).
#
# Hit live 2026-09-04 on sites/bel: `description` was declared both in
# _shared/application-priority-common.yaml and in dc/application-priority.yaml
# with different text.  The branch variant merged fine because its variant file
# declared no description at all.
#
# RULE ENFORCED HERE: for each named item of a profile list, every scalar key
# must have a single value across all the files that contribute to it.
PROFILE_LISTS = (
    "system_profiles", "transport_profiles", "service_profiles", "cli_profiles",
    "application_priority_profiles", "policy_groups",
)
for site_dir in checked_sites:
    site = pathlib.Path(site_dir).name
    scalars = {}   # (list, name, key) -> {value: [files]}
    for f in sorted(glob.glob(str(pathlib.Path(site_dir) / "data" / "*.yaml"))):
        with open(f, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        fps = doc.get("sdwan", {}).get("feature_profiles", {}) or {}
        pools = dict(fps)
        pools["policy_groups"] = doc.get("sdwan", {}).get("policy_groups", []) or []
        for plist in PROFILE_LISTS:
            for item in pools.get(plist, []) or []:
                if not isinstance(item, dict) or "name" not in item:
                    continue
                for k, v in item.items():
                    if isinstance(v, (list, dict)):
                        continue
                    scalars.setdefault((plist, item["name"], k), {}).setdefault(
                        v, []).append(pathlib.Path(f).name)
    for (plist, name, key), values in sorted(scalars.items()):
        if len(values) > 1:
            detail = "; ".join(
                f"{v!r} in {', '.join(files)}" for v, files in values.items()
            )
            errors.append(
                f"{site}: {plist} '{name}' declares conflicting '{key}' across "
                f"files ({detail}) — the merge will keep them as separate items "
                f"and terraform will abort with a duplicate for_each key. "
                f"Declare a profile's scalars in exactly ONE file."
            )

if warnings:
    print("WARNINGS:")
    for w in warnings:
        print(" -", w)
print(f"Checked sites: {[pathlib.Path(d).name for d in checked_sites]}")
if errors:
    print("FAILURES:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("All cross-checks passed: names, by-name references, variable coverage.")
