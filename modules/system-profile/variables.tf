variable "site_name" {
  description = "Site identifier used in all resource names"
  type        = string
}

variable "system_profile_id" {
  description = "ID of the system feature profile to attach parcels to"
  type        = string
}

variable "common" {
  description = "Map of decoded common/*.yaml files; keys: aaa, ntp, banner, snmp, logging"
  type        = any
}

variable "system_overrides" {
  description = "system: block from site YAML; site-level overrides merged over common values; may be null"
  type        = any
  default     = null
}

variable "tacacs_key" {
  description = "TACACS authentication key/secret; sensitive — never in YAML"
  type        = string
  sensitive   = true
  default     = ""
}
