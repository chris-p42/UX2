locals {
  # Shallow-merge common values with site-level overrides (site wins on conflict).
  # For nested maps (e.g. snmp), the site block replaces the entire sub-key.
  aaa     = merge(var.common.aaa, try(var.system_overrides.aaa, {}))
  ntp     = merge(var.common.ntp, try(var.system_overrides.ntp, {}))
  banner  = merge(var.common.banner, try(var.system_overrides.banner, {}))
  snmp    = merge(var.common.snmp, try(var.system_overrides.snmp, {}))
  logging = merge(var.common.logging, try(var.system_overrides.logging, {}))
}

resource "sdwan_system_aaa_feature" "this" {
  name               = "aaa-${var.site_name}"
  description        = "AAA / TACACS for ${var.site_name}"
  feature_profile_id = var.system_profile_id

  auth_order = local.aaa.tacacs.auth_order

  tacacs_servers = [
    for srv in local.aaa.tacacs.servers : {
      address = srv.address
      port    = srv.port
      key     = var.tacacs_key
    }
  ]
}

resource "sdwan_system_ntp_feature" "this" {
  name               = "ntp-${var.site_name}"
  description        = "NTP for ${var.site_name}"
  feature_profile_id = var.system_profile_id

  servers = [
    for srv in local.ntp.servers : {
      name = srv.address
      vpn  = srv.vpn
    }
  ]

  timezone = local.ntp.timezone
}

resource "sdwan_system_banner_feature" "this" {
  name               = "banner-${var.site_name}"
  description        = "MOTD and login banner for ${var.site_name}"
  feature_profile_id = var.system_profile_id

  motd_banner  = local.banner.motd
  login_banner = local.banner.login
}

resource "sdwan_system_snmp_feature" "this" {
  name               = "snmp-${var.site_name}"
  description        = "SNMP for ${var.site_name}"
  feature_profile_id = var.system_profile_id

  communities = [
    for c in local.snmp.communities : {
      name = c.name
      type = c.type
    }
  ]

  trap_destinations = [
    for t in local.snmp.trap_destinations : {
      address = t.address
      vpn     = t.vpn
    }
  ]

  location = try(local.snmp.location, null)
  contact  = try(local.snmp.contact, null)
}

resource "sdwan_system_logging_feature" "this" {
  name               = "logging-${var.site_name}"
  description        = "Syslog for ${var.site_name}"
  feature_profile_id = var.system_profile_id

  ipv4_servers = [
    for srv in local.logging.servers : {
      address  = srv.address
      vpn      = srv.vpn
      priority = srv.priority
    }
  ]
}
