#!/usr/bin/env python3
"""
csv_to_values.py - one-time migration script.

Converts a legacy vManage device-template-attachment variable export into
per-site values/*.yaml files consumed by generate.py.

Two export formats are supported:

  Standard (one row per device, columns = variables):
    python3 csv_to_values.py devices.csv

  Transposed (vManage default: rows = variable paths, columns = devices):
    python3 csv_to_values.py devices.csv --transposed

Column names are NOT known in advance (every fabric's export differs),
so this script auto-detects the site-id / hostname / system-ip columns
by best-effort name matching and REPORTS what it guessed — always check
the printed summary before trusting the output. Override any guess with
--site-id-col / --hostname-col / --system-ip-col if auto-detect picks
the wrong column for your export.

When anonymised exports produce colliding site codes (e.g. both DC and
branch CSVs have hostname "SD-WAN01"), use --site-code to override the
derived code for that run.

Usage:
    python3 csv_to_values.py devices.csv
    python3 csv_to_values.py devices.csv --transposed --site-code BXT --site-map site-map.yaml
    python3 csv_to_values.py devices.csv --site-id-col "Site ID"
    python3 csv_to_values.py devices.csv --site-map site-map.yaml --force --out values
"""
import argparse
import csv
import pathlib
import re
import sys
from collections import defaultdict

import yaml

# Resolved path to the canonical values/ directory — used by the --force guard
# so that --out ./values, --out values/, and absolute paths are all caught.
_VALUES_DIR = pathlib.Path(__file__).resolve().parent / "values"

# ---------------------------------------------------------------------------
# RENAME_MAP  source-column-name → target device_variables key
#
# Populated from the real UX1 exports (branch CSV + DC CSV).  Any column
# not listed here passes through normalised (lower-case, non-alnum → "_").
# The unmapped list is printed at the end so you can add entries and re-run.
# ---------------------------------------------------------------------------
RENAME_MAP = {
    # --- VPN 0 transport interfaces (both branch and DC share names) ---
    "/0/vpn0_custom1_if_name/interface/if-name":                          "vpn0_inet1_ifname",
    "/0/vpn0_custom1_if_name/interface/ip/address":                       "vpn0_inet1_ip",
    "/0/vpn0_custom1_if_name/interface/description":                      "vpn0_inet1_desc",
    "/0/vpn0_custom1_if_name/interface/bandwidth-downstream":             "vpn0_inet1_bw_down",
    "/0/vpn0_custom1_if_name/interface/shaping-rate":                     "vpn0_inet1_shape",
    "/0/vpn0_custom1_if_name/interface/shutdown":                         "vpn0_inet1_shutdown",
    "/0/vpn0_custom1_if_name/interface/tunnel-interface/color/value":     "vpn0_inet1_color",
    "/0/vpn0_custom1_if_name/interface/tunnel-interface/encapsulation/ipsec/preference": "vpn0_inet1_pref",

    "/0/vpn0_custom2_if_name/interface/if-name":                          "vpn0_inet2_ifname",
    "/0/vpn0_custom2_if_name/interface/ip/address":                       "vpn0_inet2_ip",
    "/0/vpn0_custom2_if_name/interface/description":                      "vpn0_inet2_desc",
    "/0/vpn0_custom2_if_name/interface/bandwidth-downstream":             "vpn0_inet2_bw_down",
    "/0/vpn0_custom2_if_name/interface/shaping-rate":                     "vpn0_inet2_shape",
    "/0/vpn0_custom2_if_name/interface/shutdown":                         "vpn0_inet2_shutdown",
    "/0/vpn0_custom2_if_name/interface/tunnel-interface/color/value":     "vpn0_inet2_color",
    "/0/vpn0_custom2_if_name/interface/tunnel-interface/encapsulation/ipsec/preference": "vpn0_inet2_pref",

    "/0/vpn0_private1-2_if_name/interface/if-name":                       "vpn0_mpls_ifname",
    "/0/vpn0_private1-2_if_name/interface/ip/address":                    "vpn0_mpls_ip",
    "/0/vpn0_private1-2_if_name/interface/description":                   "vpn0_mpls_desc",
    "/0/vpn0_private1-2_if_name/interface/bandwidth-downstream":          "vpn0_mpls_bw_down",
    "/0/vpn0_private1-2_if_name/interface/shaping-rate":                  "vpn0_mpls_shape",
    "/0/vpn0_private1-2_if_name/interface/shutdown":                      "vpn0_mpls_shutdown",
    "/0/vpn0_private1-2_if_name/interface/autonegotiate":                 "vpn0_mpls_autoneg",
    "/0/vpn0_private1-2_if_name/interface/tunnel-interface/color/value":  "vpn0_mpls_color",
    "/0/vpn0_private1-2_if_name/interface/tunnel-interface/encapsulation/ipsec/preference": "vpn0_mpls_pref",

    # --- TLOC-EXT (branch-a only) ---
    "/0/vpn0_tloc-ext_parent_int/interface/if-name":                      "tloc_ext_parent_ifname",
    "/0/vpn0_tloc-ext_parent_int/interface/description":                  "tloc_ext_parent_desc",
    "/0/vpn0_tloc-ext_parent_int/interface/shutdown":                     "tloc_ext_parent_shutdown",

    "/0/vpn0_tloc-ext_relay_int/interface/if-name":                       "tloc_ext_relay_ifname",
    "/0/vpn0_tloc-ext_relay_int/interface/ip/address":                    "tloc_ext_relay_ip",
    "/0/vpn0_tloc-ext_relay_int/interface/description":                   "tloc_ext_relay_desc",
    "/0/vpn0_tloc-ext_relay_int/interface/shutdown":                      "tloc_ext_relay_shutdown",
    "/0/vpn0_tloc-ext_relay_int/interface/tloc-extension":                "tloc_ext_relay_parent",

    "/0/vpn0_tloc-ext_tunnel_int/interface/if-name":                      "tloc_ext_tunnel_ifname",
    "/0/vpn0_tloc-ext_tunnel_int/interface/ip/address":                   "tloc_ext_tunnel_ip",
    "/0/vpn0_tloc-ext_tunnel_int/interface/description":                  "tloc_ext_tunnel_desc",
    "/0/vpn0_tloc-ext_tunnel_int/interface/bandwidth-downstream":         "tloc_ext_tunnel_bw_down",
    "/0/vpn0_tloc-ext_tunnel_int/interface/shaping-rate":                 "tloc_ext_tunnel_shape",
    "/0/vpn0_tloc-ext_tunnel_int/interface/shutdown":                     "tloc_ext_tunnel_shutdown",
    "/0/vpn0_tloc-ext_tunnel_int/interface/tunnel-interface/color/value": "tloc_ext_tunnel_color",
    "/0/vpn0_tloc-ext_tunnel_int/interface/tunnel-interface/encapsulation/ipsec/preference": "tloc_ext_tunnel_pref",

    # --- VPN 0 routing ---
    # branch paths use vpn0_br_dns_*; DC paths use vpn0_dns_* — map both to same key
    "/0/vpn-instance/dns/vpn0_br_dns_primary/dns-addr":                   "vpn0_dns_primary",
    "/0/vpn-instance/dns/vpn0_br_dns_secondary/dns-addr":                 "vpn0_dns_secondary",
    "/0/vpn-instance/dns/vpn0_dns_primary/dns-addr":                      "vpn0_dns_primary",
    "/0/vpn-instance/dns/vpn0_dns_secondary/dns-addr":                    "vpn0_dns_secondary",

    "/0/vpn-instance/ip/route/vpn0_cust1_ipv4_ip_prefix/next-hop/vpn0_cust1_next_hop_ip_address_0/address": "vpn0_gw_inet1",
    "/0/vpn-instance/ip/route/vpn0_cust2_ipv4_ip_prefix/next-hop/vpn0_cust2_next_hop_ip_address_0/address": "vpn0_gw_inet2",
    "/0/vpn-instance/ip/route/vpn0_priv1_ipv4_ip_prefix/next-hop/vpn0_priv1_next_hop_ip_address_0/address": "vpn0_gw_mpls1",
    "/0/vpn-instance/ip/route/vpn0_priv2_ipv4_ip_prefix/next-hop/vpn0_priv2_next_hop_ip_address_0/address": "vpn0_gw_mpls2",
    "/0/vpn-instance/ip/route/vpn0_cust1_ipv4_ip_prefix/prefix":         "vpn0_default_route",
    "/0/vpn-instance/ip/route/vpn0_cust2_ipv4_ip_prefix/prefix":         "vpn0_default_route",
    "/0/vpn-instance/ip/route/vpn0_priv1_ipv4_ip_prefix/prefix":         "vpn0_default_route",
    "/0/vpn-instance/ip/route/vpn0_priv2_ipv4_ip_prefix/prefix":         "vpn0_default_route",
    # DC routing (single default route, multiple next-hops with bracket in path)
    "/0/vpn-instance/ip/route/vpn0_ipv4_ip_prefix/prefix":               "vpn0_default_route",
    "/0/vpn-instance/ip/route/vpn0_ipv4_ip_prefix/next-hop/vpn0_Cus1_next_hop_ip_addr]/address": "vpn0_gw_inet1",
    "/0/vpn-instance/ip/route/vpn0_ipv4_ip_prefix/next-hop/vpn0_Cus2_next_hop_ip_addr]/address": "vpn0_gw_inet2",
    "/0/vpn-instance/ip/route/vpn0_ipv4_ip_prefix/next-hop/vpn0_Pri1_next_hop_ip_addr/address":  "vpn0_gw_mpls1",
    "/0/vpn-instance/ip/route/vpn0_ipv4_ip_prefix/next-hop/vpn0_Pri2_next_hop_ip_addr/address":  "vpn0_gw_mpls2",

    # --- VPN 0 OSPF ---
    "/0//router/ospf/router-id":                                          "vpn0_ospf_router_id",
    "/0//router/ospf/area/172/interface/vpn0_ospf_name/name":             "vpn0_ospf_private_if",
    "/0//router/ospf/area/172/interface/vpn0_tloc_ospf_name/name":        "vpn0_ospf_tloc_if",

    # --- VPN 10 service ---
    "/10/loopback10/interface/ip/address":                                "loopback10_ip",
    "/10/loopback10/interface/shutdown":                                  "loopback10_shutdown",

    "/10//router/bgp/router-id":                                          "bgp_router_id",
    "/10//router/bgp/neighbor/bgp_neighbor_address_SDA_CORP/address":     "bgp_neighbor_corp",
    "/10//router/bgp/neighbor/bgp_neighbor_address_SDA_INFRA/address":    "bgp_neighbor_infra",
    "/10//router/bgp/neighbor/bgp_neighbor_address_SDA_CORP/address-family/ipv4-unicast/route-policy/out/pol-name": "bgp_out_policy_corp",
    "/10//router/bgp/neighbor/bgp_neighbor_address_SDA_INFRA/address-family/ipv4-unicast/route-policy/out/pol-name": "bgp_out_policy_infra",
    "bgp_neighbor_address_SDA_CORP":                                      "bgp_neighbor_corp",
    "bgp_neighbor_address_SDA_INFRA":                                     "bgp_neighbor_infra",

    "/10//router/ospf/router-id":                                         "vpn10_ospf_router_id",
    "/10//router/ospf/redistribute/omp/route-policy":                     "vpn10_ospf_redist_policy",

    "/10/vpn10_lan_if_svi_vlan_corp_if_name/interface/if-name":           "svi_corp_ifname",
    "/10/vpn10_lan_if_svi_vlan_corp_if_name/interface/ip/address":        "svi_corp_ip",
    "/10/vpn10_lan_if_svi_vlan_corp_if_name/interface/shutdown":          "svi_corp_shutdown",
    "/10/vpn10_lan_if_svi_vlan_infra_if_name/interface/if-name":          "svi_infra_ifname",
    "/10/vpn10_lan_if_svi_vlan_infra_if_name/interface/ip/address":       "svi_infra_ip",
    "/10/vpn10_lan_if_svi_vlan_infra_if_name/interface/shutdown":         "svi_infra_shutdown",
    "vpn10_lan_if_svi_vlan_corp_if_name":                                 "svi_corp_label",
    "vpn10_lan_if_svi_vlan_infra_if_name":                                "svi_infra_label",

    "/10/Vlan62/interface/ip/address":                                    "vlan62_ip",
    "/10/Vlan62/interface/vrrp/62/ipv4/address":                          "vlan62_vrrp_ip",
    "/10/Vlan62//dhcp-server/address-pool":                               "vlan62_dhcp_pool",
    "/10/Vlan62//dhcp-server/options/default-gateway":                    "vlan62_dhcp_gw",
    "/10/Vlan253/interface/ip/address":                                   "vlan253_ip",
    "/10/Vlan253//dhcp-server/address-pool":                              "vlan253_dhcp_pool",
    "/10/Vlan253//dhcp-server/options/default-gateway":                   "vlan253_dhcp_gw",

    # --- VPN 512 management (DC only) ---
    # Note: vpn512_ifname has no CSV column — the interface name is embedded
    # in the path key itself (/512/GigabitEthernet0/...) and must be set
    # manually in the output file (always GigabitEthernet0 on C8500-12X).
    "/512/GigabitEthernet0/interface/ip/address":                         "vpn512_ip",
    "/512/vpn-instance/ip/route/0.0.0.0/0/next-hop/vpn512_next_hop_ip/address": "vpn512_gateway",

    # --- Switchport (branch only) ---
    "//switchport/interface/GigabitEthernet0/1/1/shutdown":               "sw_gi011_shutdown",
    "//switchport/interface/GigabitEthernet0/1/1/switchport/trunk/allowed/vlan/vlans": "sw_gi011_vlans",

    # --- System ---
    "//system/clock/timezone":                                            "timezone",
    "//system/port-offset":                                               "port_offset",
    "//system/gps-location/latitude":                                     "gps_lat",
    "//system/gps-location/longitude":                                    "gps_lon",

    # --- ThousandEyes (both) ---
    "//virtual-applications/virtual-application/ac1dfa01-f257-432b-a51d-cd6997b8d957/te/te-mgmt-ip": "te_mgmt_ip",
    "//virtual-applications/virtual-application/ac1dfa01-f257-432b-a51d-cd6997b8d957/te/te-vpg-ip":  "te_vpg_ip",

    # --- Misc / shorthand variables ---
    "DR-RPI":               "dr_rpi",
    "Private Interface":    "private_interface",
    "Speed Auto Negociation": "speed_autoneg",
    "Vlan CORP number":     "vlan_corp_number",
    "Vlan number":          "vlan_number",
    "IP address":           "ip_address",
    "mask":                 "mask",
    "ospf_cost":            "ospf_cost",

    # --- Identity cols (handled separately, listed here to silence unmapped warnings) ---
    # "//system/host-name"  → hostname  (detected via --hostname-col / HOSTNAME_HINTS)
    # "//system/system-ip"  → system_ip (detected via --system-ip-col / SYSTEM_IP_HINTS)
    # "//system/site-id"    → site_id   (detected via --site-id-col / SITE_ID_HINTS)
    # "csv-deviceId"        skipped (not a NaC variable)
    # "csv-deviceIP"        skipped (duplicate of system-ip)
    # "csv-host-name"       skipped (duplicate of host-name)
    # "csv-status"          skipped
}

# Columns to silently drop (device metadata, not NaC variables).
SKIP_COLS = {"csv-deviceId", "csv-deviceIP", "csv-host-name", "csv-status"}

# Auto-detected by case-insensitive substring match, first hit wins.
# Override with the --*-col flags if these guess wrong for your export.
SITE_ID_HINTS   = ["site-id", "site_id", "siteid"]
HOSTNAME_HINTS  = ["hostname", "host-name", "device-name", "device_name", "name"]
SYSTEM_IP_HINTS = ["system-ip", "system_ip", "systemip"]


def detect_column(fieldnames, hints, override=None):
    if override:
        if override not in fieldnames:
            sys.exit(f"Column '{override}' not found in CSV. Available: {fieldnames}")
        return override
    lowered = {f.lower(): f for f in fieldnames}
    for hint in hints:
        for lower_name, real_name in lowered.items():
            if hint in lower_name:
                return real_name
    return None


def load_rows(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    if not rows:
        sys.exit(f"No data rows found in {csv_path}")
    return list(fieldnames), rows


def transpose_csv(csv_path):
    """Read a vManage transposed export (rows=variable-paths, cols=devices)
    and return (fieldnames, rows) in the standard one-row-per-device format.

    Input header:  configurationPath | Device1 | Device2 | ...
    Input rows:    /some/path        | val1    | val2    | ...

    Output fieldnames: ['/some/path', '/other/path', ...]
    Output rows:       [{'//system/host-name': 'Device1', ...}, ...]
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        all_rows = [r for r in reader if any(cell.strip() for cell in r)]

    if len(all_rows) < 2:
        sys.exit(f"Not enough rows in {csv_path} for transposed format")

    header = all_rows[0]          # e.g. ["configurationPath", "SD-WAN01", "SD-WAN02"]
    device_count = len(header) - 1
    devices = [{} for _ in range(device_count)]
    fieldnames = []

    for row in all_rows[1:]:
        path = row[0]
        fieldnames.append(path)
        for i in range(device_count):
            devices[i][path] = row[i + 1] if i + 1 < len(row) else ""

    return fieldnames, devices


def rename_row(row, identity_cols):
    """Rename every non-identity, non-skip column via RENAME_MAP; anything
    unmapped passes through under a normalised version of its original name.
    Returns (renamed_dict, list_of_unmapped_source_column_names)."""
    out = {}
    unmapped = []
    for key, value in row.items():
        if key in identity_cols or key in SKIP_COLS:
            continue
        target = RENAME_MAP.get(key)
        if target is None:
            target = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
            unmapped.append(key)
        out[target] = value
    return out, unmapped


def load_site_map(path):
    if path is None:
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def derive_site_code(hostname, site_id):
    """Strip a trailing router-number suffix (-r1, -r2, r01, ...) from the
    first device's hostname to get a site code."""
    stripped = re.sub(r"[-_]?r?\d+$", "", hostname, flags=re.IGNORECASE)
    return (stripped or str(site_id)).upper()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv_path", help="Path to the device-variable CSV export")
    parser.add_argument(
        "--transposed",
        action="store_true",
        help="CSV is in vManage transposed format (rows=variable-paths, "
             "cols=devices). Converts to one-row-per-device before processing.",
    )
    parser.add_argument(
        "--site-code",
        help="Override the site code derived from the first device hostname. "
             "Needed when anonymised hostnames produce colliding or wrong codes.",
    )
    parser.add_argument("--site-id-col",   help="Override auto-detected site-id column")
    parser.add_argument("--hostname-col",  help="Override auto-detected hostname column")
    parser.add_argument("--system-ip-col", help="Override auto-detected system-ip column")
    parser.add_argument(
        "--site-map",
        help="YAML file of {site_code: variant}. Sites missing from it get "
             "variant: TODO-ASSIGN-VARIANT rather than a silent guess.",
    )
    parser.add_argument(
        "--out",
        default="values.generated",
        help="Output directory (default: values.generated/, never values/ directly)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required to write into values/ itself instead of the staging dir",
    )
    args = parser.parse_args()

    if pathlib.Path(args.out).resolve() == _VALUES_DIR and not args.force:
        sys.exit(
            "Refusing to write into values/ without --force "
            "— write to values.generated/ and diff first."
        )

    if args.transposed:
        fieldnames, rows = transpose_csv(args.csv_path)
        print(f"Transposed: {len(fieldnames)} variable paths -> {len(rows)} device rows")
    else:
        fieldnames, rows = load_rows(args.csv_path)
        print(f"Detected {len(fieldnames)} columns: {fieldnames}")

    site_id_col   = detect_column(fieldnames, SITE_ID_HINTS,   args.site_id_col)
    hostname_col  = detect_column(fieldnames, HOSTNAME_HINTS,  args.hostname_col)
    system_ip_col = detect_column(fieldnames, SYSTEM_IP_HINTS, args.system_ip_col)

    for label, col in [
        ("site-id",   site_id_col),
        ("hostname",  hostname_col),
        ("system-ip", system_ip_col),
    ]:
        if col is None:
            sys.exit(
                f"Could not auto-detect the {label} column. Re-run with the "
                f"matching --*-col flag. Columns present: {fieldnames}"
            )
        print(f"Using '{col}' as the {label} column")

    identity_cols = {site_id_col, hostname_col, system_ip_col}

    sites = defaultdict(list)
    for row in rows:
        sites[row[site_id_col]].append(row)

    if args.site_code and len(sites) > 1:
        sys.exit(
            f"--site-code {args.site_code!r} given but CSV contains "
            f"{len(sites)} distinct site-ids — all would collapse to the "
            f"same output file. Pass a single-site CSV or omit --site-code."
        )

    site_map = load_site_map(args.site_map)

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    unmapped_columns = set()
    needs_variant    = []
    bad_device_count = []

    for site_id, device_rows in sites.items():
        if len(device_rows) != 2:
            bad_device_count.append((site_id, len(device_rows)))

        device_rows_sorted = sorted(device_rows, key=lambda r: r[hostname_col])

        if args.site_code:
            site_code = args.site_code.upper()
        else:
            site_code = derive_site_code(
                device_rows_sorted[0][hostname_col], site_id
            )

        variant = site_map.get(site_code)
        if variant is None:
            variant = "TODO-ASSIGN-VARIANT"
            needs_variant.append(site_code)

        site_id_value = device_rows_sorted[0][site_id_col]
        site_id_out = (
            int(site_id_value) if str(site_id_value).isdigit() else site_id_value
        )

        device_variables = {}
        for i, row in enumerate(device_rows_sorted, start=1):
            renamed, unmapped = rename_row(row, identity_cols)
            unmapped_columns.update(unmapped)
            device_variables[f"router{i}"] = {
                "hostname":  row[hostname_col],
                "system_ip": row[system_ip_col],
                "site_id":   site_id_out,
                **renamed,
            }

        out_data = {
            "site_code":        site_code,
            "variant":          variant,
            "site_id":          site_id_out,
            "device_variables": device_variables,
        }

        out_path = out_dir / f"{site_code.lower()}.yaml"
        with out_path.open("w") as f:
            yaml.safe_dump(out_data, f, sort_keys=False, allow_unicode=True)
        print(f"Wrote {out_path}")

    print("\n=== Summary ===")
    print(f"Sites converted: {len(sites)}")
    if bad_device_count:
        print(
            "Sites with device count != 2 (check for spares/controllers): "
            f"{bad_device_count}"
        )
    if unmapped_columns:
        print(
            "Columns with no RENAME_MAP entry (passed through as-is; add a "
            f"rename if the name is bad): {sorted(unmapped_columns)}"
        )
    if needs_variant:
        print(
            f"Sites needing manual `variant:` assignment (add to --site-map): "
            f"{sorted(needs_variant)}"
        )
    print(f"\nOutput in {out_dir}/ — diff against values/ before adopting.")


if __name__ == "__main__":
    main()
