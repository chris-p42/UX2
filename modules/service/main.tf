locals {
  # Index service VPNs by VPN number (string key for for_each)
  vpn_map = { for v in var.service_vpns : tostring(v.vpn) => v }

  # Flatten service_vpns → campus_interface.vrfs → [cedge_a, cedge_b] into a single map.
  # CRITICAL: port lives at campus_interface level, NOT inside vrf.
  # Carry it explicitly so it's available as each.value.port.
  campus_peers = {
    for item in flatten([
      for vpn in var.service_vpns : [
        for vrf in vpn.campus_interface.vrfs : [
          for cedge_key in ["cedge_a", "cedge_b"] : {
            key       = "${vpn.vpn}-${vrf.name}-${cedge_key}"
            vpn       = vpn.vpn
            port      = vpn.campus_interface.port  # MUST be explicit — not in vrf object
            vrf       = vrf
            cedge     = vrf[cedge_key]
            cedge_key = cedge_key
          }
        ]
      ]
    ]) : item.key => item
  }

  bgp_peers  = { for k, v in local.campus_peers : k => v if v.cedge.bgp != null }
  ospf_peers = { for k, v in local.campus_peers : k => v if v.cedge.ospf != null }

  # Named route-map policies that have at least one non-null field
  route_maps_active = {
    for k, v in try(one(var.service_vpns).route_maps, {}) : k => v
    if anytrue([for attr in values(v) : attr != null])
  }
}

# Service LAN VPN containers — one per VPN >= 1
resource "sdwan_service_lan_vpn_feature" "this" {
  for_each = local.vpn_map

  name               = "vpn${each.key}-${var.site_name}"
  description        = "Service VPN ${each.key}"
  feature_profile_id = var.service_profile_id
  vpn                = each.value.vpn
  vpn_name           = each.value.name
}

# Campus sub-interfaces — one per (VPN, VRF, cEdge)
# interface_name = "<port>.<vlan>", e.g. GigabitEthernet6.3110
resource "sdwan_service_lan_vpn_interface_ethernet_feature" "campus" {
  for_each = local.campus_peers

  name                       = "campus-${var.site_name}-${each.key}"
  description                = "Campus trunk sub-interface ${each.key}"
  feature_profile_id         = var.service_profile_id
  service_lan_vpn_feature_id = sdwan_service_lan_vpn_feature.this[tostring(each.value.vpn)].id

  interface_name   = "${each.value.port}.${each.value.cedge.vlan}"
  shutdown         = false
  vlan_id          = each.value.cedge.vlan
  ipv4_address     = each.value.cedge.ip
  ipv4_subnet_mask = each.value.cedge.mask
}

# BGP campus peering — one resource per (VPN, VRF, cEdge) where bgp is non-null
resource "sdwan_service_routing_bgp_feature" "this" {
  for_each = local.bgp_peers

  name                       = "bgp-${substr("${var.site_name}-${each.key}", 0, 28)}"
  description                = substr("${var.site_name} ${each.key}", 0, 32)
  feature_profile_id         = var.service_profile_id
  service_lan_vpn_feature_id = sdwan_service_lan_vpn_feature.this[tostring(each.value.vpn)].id

  as_number = tostring(var.globals.sdwan_as)

  ipv4_neighbors = [
    {
      address     = each.value.cedge.bgp.neighbor_ip
      description = substr("${var.site_name} ${each.key}", 0, 32)
      remote_as   = tostring(var.globals.campus_as)

      # Route-map references — resolve by name from sdwan_service_route_policy_feature
      route_policy_in  = try(sdwan_service_route_policy_feature.this[each.value.cedge.bgp.route_map_in].id, null)
      route_policy_out = try(sdwan_service_route_policy_feature.this[each.value.cedge.bgp.route_map_out].id, null)
    }
  ]

  # OMP → campus: redistribute per VRF (redistribute_omp is per VRF, not per cEdge)
  ipv4_redistributes = each.value.vrf.redistribute_omp ? [{ protocol = "omp" }] : []

  depends_on = [sdwan_service_lan_vpn_interface_ethernet_feature.campus]
}

# OSPF campus peering — one resource per (VPN, VRF, cEdge) where ospf is non-null
resource "sdwan_service_routing_ospf_feature" "this" {
  for_each = local.ospf_peers

  name                       = "ospf-svc-${var.site_name}-${substr(each.key, 0, 20)}"
  description                = "OSPF campus peering ${each.key}"
  feature_profile_id         = var.service_profile_id
  service_lan_vpn_feature_id = sdwan_service_lan_vpn_feature.this[tostring(each.value.vpn)].id

  ospf_areas = [
    {
      area_number = each.value.cedge.ospf.area
      interfaces  = [{ name = "${each.value.port}.${each.value.cedge.vlan}" }]
    }
  ]

  # OMP → campus: redistribute per VRF
  redistribute = each.value.vrf.redistribute_omp ? [{ protocol = "omp" }] : []

  depends_on = [sdwan_service_lan_vpn_interface_ethernet_feature.campus]
}

# Named route-map policies — one per entry in site YAML route_maps with at least one non-null field
resource "sdwan_service_route_policy_feature" "this" {
  for_each = local.route_maps_active

  name               = "rmap-${var.site_name}-${each.key}"
  description        = "Route-map policy ${each.key} for ${var.site_name}"
  feature_profile_id = var.service_profile_id

  sequences = [
    {
      id   = 1
      name = each.key

      match_entries = each.value.prefix_list != null ? [
        { ipv4_prefix_list_ids = [sdwan_policy_object_prefix_list.this[each.key].id] }
      ] : []

      actions = [
        {
          set_local_pref = each.value.set_local_pref
          set_med        = each.value.set_med
          set_community  = each.value.set_community
          as_path_prepend = each.value.as_path_prepend
        }
      ]
    }
  ]
}

# Prefix lists for route-maps that reference one
resource "sdwan_policy_object_prefix_list" "this" {
  for_each = { for k, v in local.route_maps_active : k => v if v.prefix_list != null }

  name        = "pfxlist-${var.site_name}-${each.key}"
  description = "Prefix list for route-map ${each.key} at ${var.site_name}"

  entries = each.value.prefix_list
}
