output "vpn0_feature_id" {
  description = "ID of the VPN 0 transport container feature; used by modules/tloc-ext"
  value       = sdwan_transport_wan_vpn_feature.vpn0.id
}

output "config_group_id" {
  description = "Not applicable at transport module level; surfaced by modules/site"
  value       = null
}

output "device_ids" {
  description = "Not applicable at transport module level; surfaced by modules/site"
  value       = []
}
