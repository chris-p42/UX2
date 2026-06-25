# regions/na/policy/main.tf
# ISOLATED STACK — regional policy only. Apply this FIRST before any site stack.
# Outputs policy_id; each site stack reads it via terraform_remote_state.

locals {
  globals = yamldecode(file("${path.module}/../../../globals.yaml"))
  policy  = yamldecode(file("${path.module}/../policy.yaml"))
}

module "regional_policy" {
  source      = "../../../modules/policy-group"
  region_name = "na"
  policy_cfg  = local.policy
  dc_hub      = local.globals.dc_hub
}
