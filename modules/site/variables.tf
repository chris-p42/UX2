variable "site_name" {
  description = "Site identifier used in all resource names (e.g. nyc, dc-hub)"
  type        = string
}

variable "site_cfg" {
  description = "Decoded site YAML; full site configuration object"
  type        = any
}

variable "globals" {
  description = "Decoded globals.yaml; provides sdwan_as, campus_as, dc_hub"
  type        = any
}

variable "common" {
  description = "Map of decoded common/*.yaml files; keys: aaa, ntp, banner, snmp, logging"
  type        = any
}

variable "regional_policy_id" {
  description = "ID of the regional centralized policy; read from policy/ sub-stack via terraform_remote_state"
  type        = string
}

variable "tacacs_key" {
  description = "TACACS authentication key; sensitive — not in YAML"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ospf_md5_secret" {
  description = "OSPF MD5 secret for campus OSPF (DC hub only); sensitive — passed as vManage device variable"
  type        = string
  sensitive   = true
  default     = ""
}
