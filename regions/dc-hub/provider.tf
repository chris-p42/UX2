terraform {
  required_providers {
    sdwan = {
      source  = "CiscoDevNet/sdwan"
      version = ">= 0.3.0"
    }
  }

  backend "local" {}
}

provider "sdwan" {
  url      = var.sdwan_url
  username = var.sdwan_username
  password = var.sdwan_password
  insecure = var.sdwan_insecure
}
