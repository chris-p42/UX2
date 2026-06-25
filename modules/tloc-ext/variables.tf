variable "site_name" {
  description = "Site identifier used in all resource names"
  type        = string
}

variable "transport_profile_id" {
  description = "ID of the transport feature profile"
  type        = string
}

variable "vpn0_feature_id" {
  description = "ID of the VPN 0 transport container; TLOC-EXT sub-interfaces attach here"
  type        = string
}

variable "tloc_ext" {
  description = "tloc_ext block from site YAML; module is only called when non-null"
  type        = any
}
