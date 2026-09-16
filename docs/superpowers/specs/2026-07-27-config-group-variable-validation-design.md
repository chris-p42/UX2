# Configuration-Group Variable Validation Design

## Goal

Make the BXT UX2 configuration group pass vManage schema validation while retaining `netascode/nac-sdwan/sdwan` version 1.4.0 and preserving generated-site ownership rules.

## Root causes

1. `bgp_features[].neighbors` is not consumed by NaC 1.4.0; the supported collection is `ipv4_neighbors`. As a result, the BGP neighbor variables were sent during device attachment but were never declared by the BGP feature parcel.
2. The Cisco provider requires `ipv4_address_type: static` when an Ethernet interface uses `ipv4_address_variable`. Omitting it causes persistent refresh drift and prevents address variables from appearing in the configuration-group schema.
3. `te_mgmt_ip`, `te_vpg_ip`, `bgp_out_policy_corp`, and `bgp_out_policy_infra` are not referenced by any active BXT feature template but were emitted as device variables.
4. Live validation and provider source confirm `pseudo_commit_timer: 0` is a required config-group system device variable. It is independent of the UX2 `configuration_group_deploy` gate.
5. Edge deployment requires every system profile to include Global and OMP parcels, even when all optional settings use provider/vManage defaults.

## Design

- Keep the Terraform Registry module source and version unchanged.
- Correct the branch and DC BGP collection names to `ipv4_neighbors`.
- Set `ipv4_address_type: static` on Ethernet interfaces that declare an IPv4 address variable.
- Remove unmodelled values from active BXT device variables; retain explanatory comments where useful.
- Extend `validate_model.py` so future generation fails locally for unsupported `neighbors`, missing static address type, missing `pseudo_commit_timer`, and unreferenced device variables.
- Require named default `global` and `omp` parcels in every system profile.
- Regenerate `sites/bxt/data` exclusively through `generate.py`.

## Verification

1. Run the validator before template changes and confirm it reports the known defects.
2. Apply source changes and regenerate BXT.
3. Run the validator and `terraform validate`.
4. Run `terraform plan` with credentials if available. Do not run `terraform apply` without explicit approval.
