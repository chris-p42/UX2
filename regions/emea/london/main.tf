# regions/emea/london/main.tf
# ISOLATED STACK — London site only. Apply regions/emea/policy/ first.

locals {
  globals  = yamldecode(file("${path.module}/../../../globals.yaml"))
  site_cfg = yamldecode(file("${path.module}/../sites/london.yaml"))
  common = {
    aaa     = yamldecode(file("${path.module}/../../../common/aaa.yaml"))
    ntp     = yamldecode(file("${path.module}/../../../common/ntp.yaml"))
    banner  = yamldecode(file("${path.module}/../../../common/banner.yaml"))
    snmp    = yamldecode(file("${path.module}/../../../common/snmp.yaml"))
    logging = yamldecode(file("${path.module}/../../../common/logging.yaml"))
  }
}

data "terraform_remote_state" "policy" {
  backend = "local"
  config  = { path = "${path.module}/../policy/terraform.tfstate" }
}

module "site" {
  source = "../../../modules/site"

  site_name          = "london"
  site_cfg           = local.site_cfg
  globals            = local.globals
  common             = local.common
  regional_policy_id = data.terraform_remote_state.policy.outputs.policy_id
  tacacs_key         = var.tacacs_key
}

module "policy_override" {
  count  = local.site_cfg.policy_override != null ? 1 : 0
  source = "../../../modules/policy-override"

  site_name       = "london"
  override_cfg    = local.site_cfg.policy_override
  config_group_id = module.site.config_group_id
}
