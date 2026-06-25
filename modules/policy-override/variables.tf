variable "site_name" {
  description = "Site identifier used in all resource names"
  type        = string
}

variable "config_group_id" {
  description = "ID of the site's configuration group; override parcels attach to it"
  type        = string
}

variable "override_cfg" {
  description = "policy_override block from site YAML; module is only called when non-null"
  type        = any
}
