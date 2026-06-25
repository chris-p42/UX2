output "config_group_id" {
  description = "ID of the configuration group for this site"
  value       = module.config_group.config_group_id
}

output "device_ids" {
  description = "Chassis IDs of both cEdges at this site"
  value       = [var.site_cfg.chassis_a, var.site_cfg.chassis_b]
}
