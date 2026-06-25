# CLI feature profile — container for both CLI parcels
resource "sdwan_cli_feature_profile" "this" {
  name        = "${var.site_name}-cli-addon"
  description = "CLI add-on parcels — DC hub port-channel and supplemental features"
}

# Parcel 1 — Port-channel: LAG member channel-group + Port-channel sub-interfaces per VRF
# Two-stage substitution:
#   ${...}  = templatestring() — resolved before storing in vManage (site-wide values)
#   {{...}} = vManage device variables — resolved per device at push time
resource "sdwan_cli_config_feature" "port_channel" {
  name               = "${var.site_name}-portchannel"
  description        = "LAG members + Port-channel campus sub-interfaces"
  feature_profile_id = sdwan_cli_feature_profile.this.id

  cli = templatestring(<<-EOT
%{for member in cli_addon.port_channel.members~}
interface ${member}
 no ip address
 no negotiation auto
 channel-group ${cli_addon.port_channel.id} mode ${cli_addon.port_channel.mode}
 no shutdown
!
%{endfor~}
interface Port-channel${cli_addon.port_channel.id}
!
interface Port-channel${cli_addon.port_channel.id}.{{cli_vlan_corp}}
 encapsulation dot1Q {{cli_vlan_corp}}
 vrf forwarding 10
 ip address {{cli_ip_corp}} {{cli_mask_corp}}
 ip ospf ${cli_addon.campus_ospf.process_id} area 0
 ip ospf network point-to-point
 ip ospf cost ${cli_addon.campus_ospf.cost}
 ip ospf dead-interval 20
 ip ospf hello-interval 5
 ip ospf retransmit-interval 5
 ip ospf authentication message-digest
 ip ospf message-digest-key ${cli_addon.campus_ospf.md5_key_id} md5 {{cli_ospf_md5_secret}}
 ip pim sparse-mode
 ip pim dr-priority {{cli_pim_dr_priority}}
 no shutdown
!
interface Port-channel${cli_addon.port_channel.id}.{{cli_vlan_infra}}
 encapsulation dot1Q {{cli_vlan_infra}}
 vrf forwarding 10
 ip address {{cli_ip_infra}} {{cli_mask_infra}}
 ip ospf ${cli_addon.campus_ospf.process_id} area 0
 ip ospf network point-to-point
 ip ospf cost ${cli_addon.campus_ospf.cost}
 ip ospf dead-interval 20
 ip ospf hello-interval 5
 ip ospf retransmit-interval 5
 ip ospf authentication message-digest
 ip ospf message-digest-key ${cli_addon.campus_ospf.md5_key_id} md5 {{cli_ospf_md5_secret}}
 ip pim sparse-mode
 ip pim dr-priority {{cli_pim_dr_priority}}
 no shutdown
!
EOT
  , { cli_addon = var.cli_addon })
}

# Parcel 2 — Supplemental: VLAN SVI PIM, BFD, BGP fall-over, BUF-FILTER ACL, PnP
# CRITICAL: cli_addon.bgp.as_number MUST match globals.yaml.sdwan_as in the notation
# IOS-XE displays it — mismatch creates a second router bgp process instead of
# extending the native sdwan_service_routing_bgp_feature session.
resource "sdwan_cli_config_feature" "supplemental" {
  name               = "${var.site_name}-supplemental"
  description        = "VLAN SVI PIM + BFD + BGP fall-over bfd + BUF-FILTER ACL + PnP"
  feature_profile_id = sdwan_cli_feature_profile.this.id

  cli = templatestring(<<-EOT
interface Vlan{{cli_vlan_corp}}
 vrf forwarding 10
 ip pim sparse-mode
 ip pim dr-priority {{cli_pim_dr_priority}}
 bfd template bfd1
!
ip access-list standard ACL_PIM2
 10 permit 224.0.0.0 15.255.255.255
!
ip pim vrf 10 rp-address ${cli_addon.pim.rp_address} ACL_PIM2
!
interface ${site_cfg.transports["private1"].interface}
 ${cli_addon.private_interface.speed_config}
!
bfd-template single-hop bfd1
 interval min-tx 500 min-rx 500 multiplier 3
!
interface Vlan{{cli_vlan_infra}}
 bfd template bfd1
!
router bgp ${cli_addon.bgp.as_number}
 address-family ipv4 vrf 10
  neighbor {{cli_bgp_neighbor_infra}} fall-over bfd
  neighbor {{cli_bgp_neighbor_corp}} fall-over bfd
!
ip access-list extended BUF-FILTER
 10 permit udp host ${cli_addon.buf_filter.host_a} host ${cli_addon.buf_filter.host_b}
 20 permit tcp host ${cli_addon.buf_filter.host_a} host ${cli_addon.buf_filter.host_b}
 30 permit udp host ${cli_addon.buf_filter.host_b} host ${cli_addon.buf_filter.host_a}
 40 permit tcp host ${cli_addon.buf_filter.host_b} host ${cli_addon.buf_filter.host_a}
!
pnp startup-vlan ${cli_addon.pnp_startup_vlan}
!
EOT
  , {
    cli_addon = var.cli_addon
    site_cfg  = var.site_cfg
  })
}
