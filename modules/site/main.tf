locals {
  # Route service_vpns entries: vpn 0 → transport module, vpn >= 1 → service module
  service_vpns = [for v in var.site_cfg.service_vpns : v if v.vpn != 0]

  # VRF index for device attach variables (used only when cli_addon is non-null)
  lan_vpn = length(local.service_vpns) > 0 ? one([for v in var.site_cfg.service_vpns : v if v.vpn == 10]) : null
  vrfs    = local.lan_vpn != null ? { for vrf in local.lan_vpn.campus_interface.vrfs : vrf.name => vrf } : {}
  corp    = try(local.vrfs["CORP"], null)
  infra   = try(local.vrfs["INFRA"], null)
}

# ── Feature profiles ──────────────────────────────────────────────────────

resource "sdwan_system_feature_profile" "this" {
  name        = "system-${var.site_name}"
  description = "System feature profile for ${var.site_name}"
}

resource "sdwan_transport_feature_profile" "this" {
  name        = "transport-${var.site_name}"
  description = "Transport feature profile for ${var.site_name}"
}

resource "sdwan_service_feature_profile" "this" {
  name        = "service-${var.site_name}"
  description = "Service feature profile for ${var.site_name}"
}

# ── System OMP (device-wide; campus→OMP direction) ────────────────────────
# advertise_ipv4_bgp is flat/global — never per-VPN or per-VRF

resource "sdwan_system_omp_feature" "this" {
  name               = "omp-${var.site_name}"
  description        = "OMP settings for ${var.site_name}"
  feature_profile_id = sdwan_system_feature_profile.this.id

  advertise_ipv4_bgp = var.site_cfg.omp_advertise_bgp
}

# ── System parcels (AAA, NTP, Banner, SNMP, Logging) ─────────────────────

module "system_profile" {
  source = "../system-profile"

  site_name         = var.site_name
  system_profile_id = sdwan_system_feature_profile.this.id
  common            = var.common
  system_overrides  = try(var.site_cfg.system, null)
  tacacs_key        = var.tacacs_key
}

# ── Transport parcels (VPN 0, WAN interfaces, OSPF underlay) ─────────────

module "transport" {
  source = "../transport"

  site_name            = var.site_name
  transport_profile_id = sdwan_transport_feature_profile.this.id
  transports           = var.site_cfg.transports
}

# ── TLOC extension (optional — branch sites with dual-cEdge MPLS only) ───

module "tloc_ext" {
  count  = var.site_cfg.tloc_ext != null ? 1 : 0
  source = "../tloc-ext"

  site_name            = var.site_name
  transport_profile_id = sdwan_transport_feature_profile.this.id
  vpn0_feature_id      = module.transport.vpn0_feature_id
  tloc_ext             = var.site_cfg.tloc_ext
}

# ── CLI add-on (optional — DC hub port-channel and supplemental features) ─

module "cli_addon" {
  count  = var.site_cfg.cli_addon != null ? 1 : 0
  source = "../cli-addon"

  site_name       = var.site_name
  cli_addon       = var.site_cfg.cli_addon
  site_cfg        = var.site_cfg
  ospf_md5_secret = var.ospf_md5_secret
}

# ── Service parcels (VPN 10+, campus peering BGP/OSPF, route-maps) ───────

module "service" {
  source = "../service"

  site_name          = var.site_name
  service_profile_id = sdwan_service_feature_profile.this.id
  service_vpns       = local.service_vpns
  globals            = var.globals

  depends_on = [module.cli_addon]
}

# ── Configuration group ───────────────────────────────────────────────────

module "config_group" {
  source = "../config-group"

  site_name            = var.site_name
  system_profile_id    = sdwan_system_feature_profile.this.id
  transport_profile_id = sdwan_transport_feature_profile.this.id
  service_profile_id   = sdwan_service_feature_profile.this.id
  cli_profile_id       = var.site_cfg.cli_addon != null ? module.cli_addon[0].cli_profile_id : null
}

# ── Device attach ─────────────────────────────────────────────────────────
# pseudo_commit_timer = 300 is mandatory on every attach; baked in here so
# it is never omitted on a new site.

resource "sdwan_attach_feature_device_template" "this" {
  configuration_group_id = module.config_group.config_group_id

  devices = [
    {
      id = var.site_cfg.chassis_a
      variables = merge(
        {
          pseudo_commit_timer = "300"
          system_ip           = var.site_cfg.system_ip_a
          hostname            = var.site_cfg.hostname_a
        },
        var.site_cfg.cli_addon != null && local.corp != null ? {
          cli_vlan_corp          = tostring(local.corp.cedge_a.vlan)
          cli_ip_corp            = local.corp.cedge_a.ip
          cli_mask_corp          = local.corp.cedge_a.mask
          cli_vlan_infra         = tostring(local.infra.cedge_a.vlan)
          cli_ip_infra           = local.infra.cedge_a.ip
          cli_mask_infra         = local.infra.cedge_a.mask
          cli_pim_dr_priority    = tostring(var.site_cfg.cli_addon.pim.dr_priority_a)
          cli_ospf_md5_secret    = var.ospf_md5_secret
          cli_bgp_neighbor_corp  = local.corp.cedge_a.bgp.neighbor_ip
          cli_bgp_neighbor_infra = local.infra.cedge_a.bgp.neighbor_ip
        } : {}
      )
    },
    {
      id = var.site_cfg.chassis_b
      variables = merge(
        {
          pseudo_commit_timer = "300"
          system_ip           = var.site_cfg.system_ip_b
          hostname            = var.site_cfg.hostname_b
        },
        var.site_cfg.cli_addon != null && local.corp != null ? {
          cli_vlan_corp          = tostring(local.corp.cedge_b.vlan)
          cli_ip_corp            = local.corp.cedge_b.ip
          cli_mask_corp          = local.corp.cedge_b.mask
          cli_vlan_infra         = tostring(local.infra.cedge_b.vlan)
          cli_ip_infra           = local.infra.cedge_b.ip
          cli_mask_infra         = local.infra.cedge_b.mask
          cli_pim_dr_priority    = tostring(var.site_cfg.cli_addon.pim.dr_priority_b)
          cli_ospf_md5_secret    = var.ospf_md5_secret
          cli_bgp_neighbor_corp  = local.corp.cedge_b.bgp.neighbor_ip
          cli_bgp_neighbor_infra = local.infra.cedge_b.bgp.neighbor_ip
        } : {}
      )
    }
  ]
}
