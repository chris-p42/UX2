variable "region_name" {
  description = "Region identifier; must match the regions/<name>/ folder and policy.yaml region: field"
  type        = string
}

variable "policy_cfg" {
  description = "Decoded regional policy.yaml"
  type        = any
}

variable "dc_hub" {
  description = "DC hub identity from globals.yaml (site_id, system_ip_a, system_ip_b); read-only reference"
  type        = any
}
