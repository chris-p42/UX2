#!/usr/bin/env python3
"""
nac4 overlay generator.

Reads templates/ (structure, with a `__SITE__` token) + values/ (per-site
data) + globals.yaml (fabric-wide constants) and writes ordinary NaC YAML
into sites/<site>/data/, plus a copy of the Terraform root files from
root-template/. Output under sites/ is GENERATED - never hand-edit it.
Edit templates/, values/, or globals.yaml and re-run this script instead.

Any template scalar written as `__GLOBAL:<dotted.key>__` is substituted
with that value from globals.yaml (type preserved - a list stays a list),
so a fabric-wide constant (NTP servers, DSCP mapping, ...) lives in exactly
one place instead of being repeated across template files.

Usage:
    python3 generate.py                # regenerate every site
    python3 generate.py --site bxt     # regenerate a single site (by site_code)
"""
import argparse
import pathlib
import re
import shutil
import sys

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATES = REPO_ROOT / "templates"
VALUES = REPO_ROOT / "values"
GLOBALS_PATH = REPO_ROOT / "globals.yaml"
VARIANTS_PATH = REPO_ROOT / "variants.yaml"
ROOT_TEMPLATE = REPO_ROOT / "root-template"
OUTPUT = REPO_ROOT / "sites"

GLOBAL_REF_RE = re.compile(r"^__GLOBAL:([A-Za-z0-9_.]+)__$")

# Anonymised placeholders look like NTP_SERVER_1 / TACACS_ENCRYPTED_KEY /
# ROUTER_ID_2 — two or more ALL-CAPS words joined by underscores.  Anything
# matching this in generated output almost certainly means a real value was
# never filled in, and would be pushed to devices verbatim by terraform.
PLACEHOLDER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")

KNOWN_OBJECT_NAMES_PATH = REPO_ROOT / "known_object_names.yaml"


def _load_known_object_names() -> frozenset:
    """Load the allowlist of deliberate ALL_CAPS object names from
    known_object_names.yaml.  Fails fast if the file is missing or malformed."""
    if not KNOWN_OBJECT_NAMES_PATH.exists():
        sys.exit(f"known_object_names.yaml not found at {KNOWN_OBJECT_NAMES_PATH}")
    with KNOWN_OBJECT_NAMES_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    names = data.get("names")
    if not isinstance(names, list) or not names:
        sys.exit("known_object_names.yaml: 'names' must be a non-empty list")
    return frozenset(names)


KNOWN_OBJECT_NAMES = _load_known_object_names()

def _load_variants() -> tuple:
    """Load VARIANTS and SHARED_TEMPLATES from variants.yaml (repo root)."""
    if not VARIANTS_PATH.exists():
        sys.exit(f"variants.yaml not found at {VARIANTS_PATH}")
    with VARIANTS_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    variants = data.get("variants")
    shared = data.get("shared_templates")
    if not isinstance(variants, dict) or not variants:
        sys.exit("variants.yaml: 'variants' must be a non-empty mapping")
    if not isinstance(shared, list) or not shared:
        sys.exit("variants.yaml: 'shared_templates' must be a non-empty list")
    return variants, shared


VARIANTS, SHARED_TEMPLATES = _load_variants()

REQUIRED_VALUE_KEYS = ("site_code", "variant", "site_id", "device_variables")


def load_values(site_file: pathlib.Path) -> dict:
    with site_file.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    missing = [k for k in REQUIRED_VALUE_KEYS if k not in data]
    if missing:
        raise ValueError(f"{site_file}: missing required key(s) {missing}")
    if data["variant"] not in VARIANTS:
        raise ValueError(
            f"{site_file}: unknown variant '{data['variant']}', "
            f"must be one of {sorted(VARIANTS)}"
        )
    return data


def load_globals() -> dict:
    if not GLOBALS_PATH.exists():
        return {}
    with GLOBALS_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_global(dotted_key: str, globals_data: dict):
    node = globals_data
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted_key)
        node = node[part]
    return node


def substitute_globals(node, globals_data: dict, label: str):
    """Recursively replace any scalar exactly matching __GLOBAL:<key>__
    with that value from globals.yaml, preserving its type (a list global
    substitutes in as a list, not a stringified one). Fails fast (exits)
    on an unknown key rather than leaving the placeholder in place."""
    if isinstance(node, dict):
        return {k: substitute_globals(v, globals_data, label) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute_globals(v, globals_data, label) for v in node]
    if isinstance(node, str):
        m = GLOBAL_REF_RE.match(node)
        if m:
            try:
                return resolve_global(m.group(1), globals_data)
            except KeyError:
                sys.exit(
                    f"{label}: unknown global reference '__GLOBAL:{m.group(1)}__' "
                    f"- check globals.yaml"
                )
    return node


def render_template(src: pathlib.Path, site_code: str, globals_data: dict) -> str:
    text = src.read_text(encoding="utf-8").replace("__SITE__", site_code.upper())
    if "__GLOBAL:" not in text:
        # No global refs in this file - keep the raw text as-is (preserves
        # comments). Only files that reference globals.yaml pay the cost
        # of being parsed and re-dumped as YAML.
        return text
    data = yaml.safe_load(text)
    data = substitute_globals(data, globals_data, label=f"{site_code}/{src.name}")
    return yaml.safe_dump(data, sort_keys=False)


def scan_placeholders(text: str, rel_name: str, findings: dict):
    """Record every unresolved ALL_CAPS placeholder in rendered output.

    Comments are stripped first (everything after '#' on each line) so that
    documentation mentioning e.g. a UX1 template name (LO_BR_AAA_ISE) does
    not trigger a false positive — only placeholders in actual YAML values
    are reported.  The split is naive (a '#' inside a quoted scalar also
    truncates), which is acceptable for a heuristic warning scan.

    Names in KNOWN_OBJECT_NAMES are skipped: they are deliberate SD-WAN object
    identifiers, not unfilled placeholders."""
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        for m in PLACEHOLDER_RE.finditer(code):
            if m.group(0) in KNOWN_OBJECT_NAMES:
                continue
            findings.setdefault(m.group(0), set()).add(rel_name)


def build_site_values_yaml(values: dict, globals_data: dict) -> str:
    """Emit the device-attach block wiring this site's routers to
    CG-<code>/PG-<code> with their device variables.

    SCHEMA-VALIDATED 2026-07-24 against nac-sdwan 1.4.0
    (sdwan_device_templates.tf locals.routers, sdwan_configuration_groups.tf):

      sdwan.sites[].routers[] with per-router:
        chassis_id                  REQUIRED - real device chassis/serial
                                    from vManage.  The anonymised exports
                                    did not carry it; a CHASSIS_ID_* value
                                    is emitted as a placeholder (caught by
                                    the placeholder scan) until real IDs
                                    are added to values/<site>.yaml.
        configuration_group         config group name (by reference)
        configuration_group_deploy  UX2 deploy gate - False means create
                                    everything in vManage but do NOT push
                                    to the device. This is independent of
                                    pseudo_commit_timer, a required config-
                                    group system device variable (value 0).
                                    Flip to True only when deliberately
                                    deploying a site.
        policy_group / policy_group_deploy   same pattern
        device_variables            flat name->value map consumed by the
                                    <field>_variable references in the
                                    feature-profile templates.  Identity
                                    fields (host_name / system_ip /
                                    site_id) are variables too."""
    site_code = values["site_code"].upper()

    routers = []
    for router_key in sorted(values["device_variables"]):
        dv = dict(values["device_variables"][router_key])  # copy - don't mutate source
        chassis_id = dv.pop("chassis_id", f"CHASSIS_ID_{router_key.upper()}")
        routers.append(
            {
                "chassis_id": chassis_id,
                "configuration_group": f"CG-{site_code}",
                "configuration_group_deploy": False,
                "policy_group": f"PG-{site_code}",
                "policy_group_deploy": False,
                "device_variables": {
                    "host_name": dv.pop("hostname", None),
                    "system_ip": dv.pop("system_ip", None),
                    "site_id": dv.pop("site_id", values["site_id"]),
                    **dv,
                },
            }
        )

    block = {"sdwan": {"sites": [{"routers": routers}]}}
    return yaml.safe_dump(block, sort_keys=False)


def generate_site(values_file: pathlib.Path, globals_data: dict, findings: dict) -> str:
    values = load_values(values_file)
    site_code = values["site_code"]
    variant = values["variant"]
    site_dir = OUTPUT / site_code.lower()
    data_dir = site_dir / "data"

    # Wipe ONLY data/ — never the whole site dir. With the default local
    # backend, sites/<site>/ holds terraform state (.terraform/, *.tfstate,
    # .terraform.lock.hcl); deleting those would orphan live infrastructure.
    # Wiping data/ alone still guarantees no stale template output survives
    # a regen (e.g. a file removed from VARIANTS disappears from data/ too).
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)

    for rel_path in SHARED_TEMPLATES + VARIANTS[variant]:
        src = TEMPLATES / rel_path
        rendered = render_template(src, site_code, globals_data)
        (data_dir / src.name).write_text(rendered, encoding="utf-8")
        scan_placeholders(rendered, f"{site_dir.name}/data/{src.name}", findings)

    site_values = build_site_values_yaml(values, globals_data)
    (data_dir / "site-values.yaml").write_text(site_values, encoding="utf-8")
    scan_placeholders(site_values, f"{site_dir.name}/data/site-values.yaml", findings)

    # Root .tf files are overwritten in place (copy, not rmtree+copy) so any
    # state/lock files sitting next to them are left untouched.
    for tf_file in ROOT_TEMPLATE.glob("*"):
        shutil.copy(tf_file, site_dir / tf_file.name)

    return site_dir.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site", help="Regenerate a single site (by site_code, case-insensitive)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail (exit 1) if any unresolved ALL_CAPS placeholder remains "
             "in the generated output, instead of just warning.",
    )
    args = parser.parse_args()

    # ALL values files are always loaded for the cross-site uniqueness
    # checks below — filtering them by --site first would let e.g. a
    # duplicated chassis_id slip through when regenerating a single site
    # (the exact copy-paste case the guard exists for).  --site only
    # narrows which sites get GENERATED.
    all_value_files = sorted(VALUES.glob("*.yaml"))
    if not all_value_files:
        sys.exit(f"No site value files found under {VALUES}")
    value_files = all_value_files
    if args.site:
        value_files = [f for f in all_value_files if f.stem.lower() == args.site.lower()]
        if not value_files:
            sys.exit(f"No values file found for site '{args.site}' under {VALUES}")

    globals_data = load_globals()

    # Enforce site_id uniqueness across all active values files (CLAUDE.md hard rule).
    seen_ids: dict = {}
    # Device-level uniqueness: a chassis can be associated with exactly ONE
    # config group (vManage rejects the association with CFGRP0018 — hit
    # live 2026-07-31 when a copied values file kept the source site's
    # serial), and duplicate system-ips break the overlay control plane.
    # ALL_CAPS placeholders are skipped — they may legitimately repeat and
    # the placeholder scan already reports them.
    seen_chassis: dict = {}
    seen_system_ips: dict = {}
    for vf in all_value_files:
        try:
            data = load_values(vf)
        except ValueError as e:
            sys.exit(str(e))
        sid = data["site_id"]
        # The per-router device_variables site_id is what actually reaches the
        # device attach (build_site_values_yaml lets it win), while THIS
        # top-level value feeds the uniqueness check below.  A silent mismatch
        # would let two sites collide on the deployed site-id without tripping
        # the guard (bitten once: BXT declared 1405 but deployed 3) — so any
        # divergence is a hard error.
        for router_key, dv in data["device_variables"].items():
            router_sid = dv.get("site_id", sid)
            if router_sid != sid:
                sys.exit(
                    f"{vf.name}: device_variables.{router_key}.site_id "
                    f"({router_sid}) differs from top-level site_id ({sid}) — "
                    f"they must match; the per-router value is what gets deployed"
                )
            for field, seen in (("chassis_id", seen_chassis), ("system_ip", seen_system_ips)):
                val = dv.get(field)
                if val is None or PLACEHOLDER_RE.fullmatch(str(val)):
                    continue
                ref = f"{vf.name}/{router_key}"
                if val in seen:
                    sys.exit(
                        f"Duplicate {field} '{val}': {seen[val]} and {ref} — "
                        f"must be unique across every router in values/ "
                        f"(one config group per chassis; unique system-ip per device)"
                    )
                seen[val] = ref
        if sid in seen_ids:
            sys.exit(
                f"Duplicate site_id {sid}: {seen_ids[sid]} and {vf.name} "
                f"— site_id must be globally unique (CLAUDE.md hard rule)"
            )
        seen_ids[sid] = vf.name

    generated = []
    findings = {}  # placeholder -> set of files it appears in
    for vf in value_files:
        try:
            generated.append(generate_site(vf, globals_data, findings))
        except ValueError as e:
            sys.exit(str(e))

    print(f"Generated {len(generated)} site(s): {', '.join(generated)}")
    print(f"Output under: {OUTPUT}")

    if findings:
        print(
            "\nWARNING: unresolved ALL_CAPS placeholders remain in the "
            "generated output - terraform would push these literal strings "
            "to devices:"
        )
        for placeholder in sorted(findings):
            files = ", ".join(sorted(findings[placeholder]))
            print(f"  {placeholder}: {files}")
        print(
            "Replace them in globals.yaml / templates/ / values/ and re-run "
            "before terraform plan."
        )
        if args.strict:
            sys.exit("Aborting: --strict set and placeholders remain.")

    print("Next: cd into each sites/<site>/ and run terraform init/plan there.")


if __name__ == "__main__":
    main() 
