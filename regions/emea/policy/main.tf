# regions/emea/policy/main.tf
# ISOLATED STACK — EMEA regional policy only. Apply this FIRST before any EMEA site stack.

locals {
  globals = yamldecode(file("${path.module}/../../../globals.yaml"))
  policy  = yamldecode(file("${path.module}/../policy.yaml"))
}

module "regional_policy" {
  source      = "../../../modules/policy-group"
  region_name = "emea"
  policy_cfg  = local.policy
  dc_hub      = local.globals.dc_hub
}
