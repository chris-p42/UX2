# QoS map policy object — org-wide QoS class definitions for this region
# DSCP values are always decimal integers (EF=46, AF31=26, BE=0) — never PHB keywords
resource "sdwan_qos_map_policy_definition" "this" {
  name        = "qos-map-${var.region_name}"
  description = "QoS class map for ${var.region_name} region"

  qos_schedulers = [
    for cls in var.policy_cfg.qos.classes : {
      class_map_name     = cls.name
      bandwidth_percent  = cls.bandwidth_percent
      buffer_percent     = cls.bandwidth_percent
      dscp               = cls.dscp
      scheduling         = "llq"
    }
  ]
}

# App-route SLA class definitions for this region
resource "sdwan_application_aware_routing_policy_definition" "this" {
  name        = "app-route-${var.region_name}"
  description = "App-route SLA classes for ${var.region_name} region"

  sequences = [
    for idx, sla in var.policy_cfg.app_route.sla_classes : {
      id   = (idx + 1) * 10
      name = sla.name

      match_entries = [
        { dns_application_list = null }
      ]

      action_entries = [
        {
          type = "slaClass"
          sla_class = {
            name              = sla.name
            preferred_color   = null
          }
        }
      ]
    }
  ]
}

# App-route SLA class objects (loss/latency/jitter per class)
resource "sdwan_sla_class_policy_object" "this" {
  for_each = { for sla in var.policy_cfg.app_route.sla_classes : sla.name => sla }

  name        = "sla-${var.region_name}-${each.key}"
  description = "SLA class ${each.key} for ${var.region_name}"

  entries = [
    {
      name       = each.key
      loss       = each.value.loss_percent
      latency    = each.value.latency_ms
      jitter     = each.value.jitter_ms
    }
  ]
}

# Hub-and-spoke topology centralized policy
# Hub identity comes from globals.yaml dc_hub block — never hardcoded here
resource "sdwan_centralized_policy" "this" {
  name        = "topology-${var.region_name}"
  description = "Hub-and-spoke topology policy for ${var.region_name} region"

  definitions = [
    {
      id   = sdwan_hub_and_spoke_topology_policy_definition.this.id
      type = "hubAndSpoke"
    }
  ]
}

resource "sdwan_hub_and_spoke_topology_policy_definition" "this" {
  name        = "hub-spoke-${var.region_name}"
  description = "Hub-and-spoke topology for ${var.region_name}"

  vpn_list_id = sdwan_policy_object_vpn_list.overlay.id

  topologies = [
    {
      name = "${var.region_name}-hub-spoke"
      spokes = [
        {
          site_list_id    = sdwan_policy_object_site_list.spokes.id
          hubs = [
            {
              site_list_id   = sdwan_policy_object_site_list.hub.id
              preference     = "primary"
            }
          ]
        }
      ]
    }
  ]
}

# Policy object: VPN list covering the overlay VPNs
resource "sdwan_policy_object_vpn_list" "overlay" {
  name        = "vpn-overlay-${var.region_name}"
  description = "Overlay VPNs for ${var.region_name}"
  entries     = [{ vpn = "10" }]
}

# Policy object: hub site list (DC hub only)
resource "sdwan_policy_object_site_list" "hub" {
  name        = "sites-hub-${var.region_name}"
  description = "DC hub site for ${var.region_name} topology"
  entries     = [{ site_id = tostring(var.dc_hub.site_id) }]
}

# Policy object: spoke site list — placeholder; actual spoke site IDs added per deployment
resource "sdwan_policy_object_site_list" "spokes" {
  name        = "sites-spokes-${var.region_name}"
  description = "Spoke sites for ${var.region_name} topology"
  entries     = [{ site_id = "200-299" }]
}
