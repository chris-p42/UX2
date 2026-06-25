variable "sdwan_url" {
  type = string
}

variable "sdwan_username" {
  type      = string
  sensitive = true
}

variable "sdwan_password" {
  type      = string
  sensitive = true
}

variable "sdwan_insecure" {
  type    = bool
  default = true
}

variable "tacacs_key" {
  description = "TACACS authentication key — sensitive"
  type        = string
  sensitive   = true
}
