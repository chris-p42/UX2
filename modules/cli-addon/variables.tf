variable "site_name" {
  description = "Site identifier used in all resource names"
  type        = string
}

variable "cli_addon" {
  description = "cli_addon block from site YAML; module is only called when non-null"
  type        = any
}

variable "site_cfg" {
  description = "Full site YAML config; needed for transports.private1.interface in supplemental parcel"
  type        = any
}

variable "ospf_md5_secret" {
  description = "OSPF MD5 authentication secret for campus OSPF peering; passed as vManage device variable only"
  type        = string
  sensitive   = true
  default     = ""
}
