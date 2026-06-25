variable "site_name" {
  description = "Site identifier used in all resource names"
  type        = string
}

variable "system_profile_id" {
  description = "ID of the system feature profile"
  type        = string
}

variable "transport_profile_id" {
  description = "ID of the transport feature profile"
  type        = string
}

variable "service_profile_id" {
  description = "ID of the service feature profile"
  type        = string
}

variable "cli_profile_id" {
  description = "ID of the CLI add-on feature profile; null when site has no cli_addon block"
  type        = string
  default     = null
}
