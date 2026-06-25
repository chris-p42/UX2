variable "site_name" {
  description = "Site identifier used in all resource names"
  type        = string
}

variable "service_profile_id" {
  description = "ID of the service feature profile"
  type        = string
}

variable "service_vpns" {
  description = "List of service VPN entries from site YAML, pre-filtered to vpn >= 1 by modules/site"
  type        = any
}

variable "globals" {
  description = "Decoded globals.yaml; provides sdwan_as and campus_as"
  type        = any
}
