# Parcel 1 — Extend own private1 to peer; peer will advertise it as private2
resource "sdwan_transport_wan_vpn_interface_ethernet_feature" "extend" {
  name                         = "tloc-ext-extend-${var.site_name}"
  description                  = "TLOC-EXT: own private1 → peer (peer sees as private2)"
  feature_profile_id           = var.transport_profile_id
  transport_wan_vpn_feature_id = var.vpn0_feature_id

  interface_name = var.tloc_ext.sub_if_extend.sub_interface
  shutdown       = false

  # TLOC extension cross-connect: extends private1 to the peer cEdge
  xconnect              = true
  xconnect_source_color = "private1"
}

# Parcel 2 — Receive peer's private1; advertised locally as private2
resource "sdwan_transport_wan_vpn_interface_ethernet_feature" "receive" {
  name                         = "tloc-ext-receive-${var.site_name}"
  description                  = "TLOC-EXT: receive peer private1 (advertised as private2)"
  feature_profile_id           = var.transport_profile_id
  transport_wan_vpn_feature_id = var.vpn0_feature_id

  interface_name = var.tloc_ext.sub_if_receive.sub_interface
  shutdown       = false

  xconnect              = true
  xconnect_source_color = "private2"
}
