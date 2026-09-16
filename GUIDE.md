# nac4 Operator Guide

Three everyday workflows: first run, changing a value, and adding something new.

---

## 1. First run

### Prerequisites

```
pip install -r requirements.txt        # pyyaml is the only hard dependency
```

On Windows, if `python3` is not in PATH, use `python` instead throughout.

### Fill in the anonymised placeholders

Before generating, open each file in `values/` and substitute every
ALL_CAPS placeholder with a real value:

| Placeholder | Where it appears | What to put |
|---|---|---|
| `NTP_SERVER_1` / `NTP_SERVER_2` | `globals.yaml` | NTP server FQDN or IP |
| `SYSLOG_SERVER` | `globals.yaml` | Syslog collector IP or FQDN |
| `SNMP_CONTACT_EMAIL` | `globals.yaml` | NOC contact string |
| `TACACS_SERVER_1` / `TACACS_SERVER_2` | `templates/*/aaa_tacacs.yaml` | TACACS+ server IPs |
| `TACACS_ENCRYPTED_KEY` | `templates/*/aaa_tacacs.yaml` | AES type-6 encrypted key |
| `ROUTER_ID_*` | `values/bxt.yaml`, `values/bel.yaml` | Per-router loopback/system IP |
| `BGP_*_NEIGHBOR_*` | `values/bxt.yaml`, `values/bel.yaml` | BGP peer IPs |
| `OSPF_*_INTERFACE` | `values/bxt.yaml` | Interface names for OSPF adjacency |
| `PUBLIC_INET*_IP_*` | `values/bel.yaml` | DC public transport IPs |
| `MPLS_INET*_IP_*` | `values/bel.yaml` | DC MPLS hub interface IPs |

Credentials are **never** stored in files — export them as environment variables:

```
export SDWAN_URL=https://<vmanage-ip>
export SDWAN_USERNAME=admin
export SDWAN_PASSWORD=<password>
export SDWAN_INSECURE=true        # if using a self-signed cert
export SDWAN_RETRIES=3
```

### Generate

```
python generate.py                 # regenerates every site under sites/
python generate.py --site bxt      # regenerate one site only
```

Output lands in `sites/<site>/data/` — never edit files there directly.
If generation fails, the error names the bad `__GLOBAL:<key>__` reference
or the missing required key; fix it in the source file and re-run.

### Plan and apply (one site at a time)

```
cd sites/bxt/
terraform init
terraform plan -out=tfplan
```

Review the plan output carefully. Only apply after explicit approval:

```
terraform apply tfplan
```

---

## 2. Modify a value

Choose the right layer depending on what you are changing.

### A. Fabric-wide constant (same on every site and variant)

Edit `globals.yaml`.

Example — change the primary NTP server:

```yaml
# globals.yaml
ntp:
  servers:
    - hostname: "ntp1.example.com"   # was NTP_SERVER_1
      vpn: 10
      source_interface: "Loopback10"
```

Then regenerate every site so all `sites/` outputs pick up the change:

```
python generate.py
```

Rule: only put a value here if you can confirm it is identical on both the
DC template (`LO_DC_DEVICE_TEMPLATE_V1.2`) and the branch template
(`LO_BR_C8200L_DEVICE_TEMPLATE_TEST_V1.4.0`). Anything that varies by
variant belongs in a template file, not in `globals.yaml`.

### B. Variant-specific constant (same within dc / branch-a / branch-b, but differs between them)

Edit the relevant template file under `templates/dc/` or `templates/branch/`.

Example — change the TACACS group name for all branch sites:

```yaml
# templates/branch/aaa_tacacs.yaml
aaa_server_groups:
  - name: "tacacs-mgmt"    # was tacacs-10
    ...
```

Regenerate only the affected variant (or all if unsure):

```
python generate.py          # safe to run all
```

### C. Per-site value (unique to one location)

Edit `values/<site>.yaml` — the `device_variables` block.

Example — correct the system IP for the BXT primary router:

```yaml
# values/bxt.yaml
device_variables:
  router1:
    system_ip: 172.25.0.189   # correct the IP here
```

Regenerate just that site:

```
python generate.py --site bxt
```

`site_id` must remain unique across all files in `values/`. Check before
adding a new site:

```
grep -r "site_id:" values/
```

---

## 3. Add a new config block or parcel not yet in a template

Use this when the NaC module supports a parcel that the fabric needs but
that does not yet exist anywhere in `templates/`.

The decision tree for where to add it:

```
Is the config identical on every site and variant?
  YES  --> add a key to globals.yaml, reference it from the template
  NO, varies by variant (dc vs branch)?
    YES  --> add/edit templates/dc/<file>.yaml and/or templates/branch/<file>.yaml
    NO, varies by individual site?
         --> add a variable to values/<site>.yaml and reference it in the template
```

### Step-by-step example: add a new SNMP view/group (shared, all variants)

**1. Add the value to `globals.yaml`** (if it is fabric-wide):

```yaml
# globals.yaml
snmp:
  contact: "SNMP_CONTACT_EMAIL"
  view: "snmp_v3_all"        # new
  group: "V3Group"           # new
```

**2. Reference it in the shared template** with `__GLOBAL:<dotted.key>__`:

```yaml
# templates/_shared/system.yaml  (inside the snmp: parcel)
snmp:
  enabled: true
  contact: "__GLOBAL:snmp.contact__"
  view:    "__GLOBAL:snmp.view__"    # new
  group:   "__GLOBAL:snmp.group__"  # new
```

If the value is not fabric-wide, put it directly in the template instead
of in `globals.yaml` — no token needed, just a literal value.

**3. Regenerate and inspect the output**:

```
python generate.py --site bxt
cat sites/bxt/data/system.yaml     # confirm the substitution rendered correctly
```

**4. If the parcel belongs to only one variant**, use a variant-specific file
instead of the shared template.

Example — adding a campus LAN parcel that only DC sites need:

```yaml
# templates/dc/service.yaml  (add the new block here, not in _shared/)
campus_lan:
  vlans:
    - id: 100
      name: "DATA"
```

Then add the file to `VARIANTS["dc"]` in `generate.py` if it is a new file
(already done for `aaa_tacacs.yaml`; follow the same pattern):

```python
# generate.py — VARIANTS dict
"dc": [
    "dc/service.yaml",
    "dc/transport.yaml",
    "dc/cli.yaml",
    "dc/config-group.yaml",
    "dc/aaa_tacacs.yaml",
    "dc/campus_lan.yaml",   # new
],
```

**5. Regenerate all sites** — generating a site that uses a different variant
will not include the new file (variant isolation is automatic):

```
python generate.py
```

### Key rules to keep in mind

- Never edit files under `sites/` — they are overwritten on the next `generate.py` run.
- Never write real credentials into any `.yaml` or `.tf` file.
- Never run `terraform apply` without reviewing the plan first.
- When adding a `__GLOBAL:<key>__` token, the key **must** exist in `globals.yaml`
  or `generate.py` will abort with a clear error naming the bad reference.
- `__SITE__` is plain string substitution (not YAML-aware) — only use it in
  string scalars such as names and descriptions, not as a YAML key.
