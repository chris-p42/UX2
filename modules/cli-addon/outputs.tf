output "cli_profile_id" {
  description = "ID of the CLI feature profile; passed to modules/config-group"
  value       = sdwan_cli_feature_profile.this.id
}

output "config_group_id" {
  value = null
}

output "device_ids" {
  value = []
}
