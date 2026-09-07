# Copied as-is into sites/<site>/ by generate.py - identical for every site,
# since the NaC module reads whatever YAML is under ./data regardless of
# which site it belongs to.

terraform {
  required_version = ">= 1.3.0"
}

module "sdwan" {
  source  = "netascode/nac-sdwan/sdwan"
  version = "1.4.0"

  yaml_directories = ["data"]
}
