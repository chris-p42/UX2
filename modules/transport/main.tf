locals {
  # Transport entries that carry an OSPF block (private1 underlay)
  ospf_transports = { for k, v in var.transports : k => v if try(v.ospf, null) != null }
}

# VPN 0 container — transport underlay
resource "sdwan_transport_wan_vpn_feature" "vpn0" {
  name               = "vpn0-${var.site_name}"
  description        = "VPN 0 transport underlay"
  feature_profile_id = var.transport_profile_id
  vpn                = 0
}

# WAN interface parcels — one per TLOC color in the transports map
resource "sdwan_transport_wan_vpn_interface_ethernet_feature" "this" {
  for_each = var.transports

  name                         = "wan-${var.site_name}-${each.key}"
  description                  = "WAN interface ${each.key}"
  feature_profile_id           = var.transport_profile_id
  transport_wan_vpn_feature_id = sdwan_transport_wan_vpn_feature.vpn0.id

  interface_name = each.value.interface
  shutdown       = false
  color          = each.key

  # DHCP (custom1/custom2) or static IP (private1)
  ipv4_configuration_type = try(each.value.dhcp, false) ? "dynamic" : "static"
  ipv4_address            = try(each.value.ip, null)
  ipv4_subnet_mask        = try(each.value.mask, null)
  # Static default route only when a gateway is present (no gateway for OSPF paths)
  ipv4_gateway = try(each.value.gateway, null)

  tunnel_interface = true
}

# OSPF underlay parcel — created once per transport profile when any transport
# carries an ospf block (private1 in this design)
resource "sdwan_transport_routing_ospf_feature" "this" {
  count = length(local.ospf_transports) > 0 ? 1 : 0

  name               = "ospf-transport-${var.site_name}"
  description        = "OSPF underlay — private1 toward PE"
  feature_profile_id = var.transport_profile_id

  ospf_areas = [
    for color, t in local.ospf_transports : {
      area_number = t.ospf.area
      interfaces  = [{ name = t.interface }]
    }
  ]
}
