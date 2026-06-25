# Per-site additive policy override — layers on top of the regional policy.
# Never creates a new sdwan_centralized_policy; only additional parcels.

resource "sdwan_policy_object_qos_map" "override" {
  count = try(var.override_cfg.qos, null) != null ? 1 : 0

  name        = "qos-override-${var.site_name}"
  description = "QoS override for ${var.site_name}"

  # DSCP must be decimal integer — convert if needed
  qos_schedulers = [
    {
      class_map_name    = var.override_cfg.qos.class_name
      bandwidth_percent = var.override_cfg.qos.bandwidth_percent
      buffer_percent    = var.override_cfg.qos.bandwidth_percent
    }
  ]
}

resource "sdwan_sla_class_policy_object" "override" {
  count = try(var.override_cfg.app_route, null) != null ? 1 : 0

  name        = "sla-override-${var.site_name}"
  description = "App-route SLA override for ${var.site_name}"

  entries = [
    {
      name             = var.override_cfg.app_route.sla_class
      preferred_color  = var.override_cfg.app_route.preferred_color
    }
  ]
}
