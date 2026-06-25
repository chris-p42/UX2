variable "site_name" {
  description = "Site identifier used in all resource names"
  type        = string
}

variable "transport_profile_id" {
  description = "ID of the transport feature profile to attach parcels to"
  type        = string
}

variable "transports" {
  description = "Color-keyed map of WAN transport configs from site YAML (custom1, custom2, private1)"
  type        = any
}
