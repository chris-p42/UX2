# regions/dc-hub/main.tf
# Single combined stack: policy + DC hub site in one Terraform root.
# Splitting is not needed for one site and the hub is managed with extreme care.

locals {
  globals  = yamldecode(file("${path.module}/../../globals.yaml"))
  policy   = yamldecode(file("${path.module}/policy.yaml"))
  site_cfg = yamldecode(file("${path.module}/sites/dc-hub.yaml"))
  common = {
    aaa     = yamldecode(file("${path.module}/../../common/aaa.yaml"))
    ntp     = yamldecode(file("${path.module}/../../common/ntp.yaml"))
    banner  = yamldecode(file("${path.module}/../../common/banner.yaml"))
    snmp    = yamldecode(file("${path.module}/../../common/snmp.yaml"))
    logging = yamldecode(file("${path.module}/../../common/logging.yaml"))
  }
}

module "regional_policy" {
  source      = "../../modules/policy-group"
  region_name = "dc-hub"
  policy_cfg  = local.policy
  dc_hub      = local.globals.dc_hub
}

module "site" {
  source = "../../modules/site"

  site_name          = "dc-hub"
  site_cfg           = local.site_cfg
  globals            = local.globals
  common             = local.common
  regional_policy_id = module.regional_policy.policy_id
  tacacs_key         = var.tacacs_key
  ospf_md5_secret    = var.ospf_md5_secret
}
