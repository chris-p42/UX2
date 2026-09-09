# The provider SOURCE must be declared here even though the module also
# depends on it: an unqualified `provider "sdwan"` block in the root module
# would otherwise resolve to the nonexistent hashicorp/sdwan and fail
# `terraform init`.
#
# The VERSION is pinned EXACTLY here (2026-07-29) because nothing else pins
# it: sites/ is regenerated (so a committed .terraform.lock.hcl never
# survives) and the nac-sdwan 1.4.0 module only constrains ~> 0.11.1 —
# even a `~>` patch pin would let a new release (0.11.4 already exists)
# drift in silently and change plan behaviour against the live fabric.
# 0.11.3 is the version the BXT deploy was validated with.  To upgrade:
# bump this value deliberately, `terraform init -upgrade`, and re-plan
# EVERY site before applying anything.

terraform {
  required_providers {
    sdwan = {
      source  = "CiscoDevNet/sdwan"
      version = "0.11.3"
    }
  }
}

provider "sdwan" {
  # Credentials via env vars only - never hardcode here:
  #   SDWAN_USERNAME, SDWAN_PASSWORD, SDWAN_URL (port goes inside the URL,
  #   there is no separate port argument), SDWAN_INSECURE, SDWAN_RETRIES
}
