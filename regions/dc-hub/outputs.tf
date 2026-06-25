output "config_group_id" {
  description = "Configuration group ID for the DC hub"
  value       = module.site.config_group_id
}

output "device_ids" {
  description = "Chassis IDs of both DC hub cEdges"
  value       = module.site.device_ids
}
