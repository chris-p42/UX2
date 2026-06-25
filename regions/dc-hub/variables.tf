variable "sdwan_url" {
  description = "vManage URL including port (e.g. https://vmanage.acme.corp:8443)"
  type        = string
}

variable "sdwan_username" {
  description = "vManage username"
  type        = string
  sensitive   = true
}

variable "sdwan_password" {
  description = "vManage password"
  type        = string
  sensitive   = true
}

variable "sdwan_insecure" {
  description = "Skip TLS certificate verification"
  type        = bool
  default     = true
}

variable "tacacs_key" {
  description = "TACACS authentication key — sensitive; never in YAML or state output"
  type        = string
  sensitive   = true
}

variable "ospf_md5_secret" {
  description = "OSPF MD5 secret for DC hub campus peering (CLI add-on device variable)"
  type        = string
  sensitive   = true
}
