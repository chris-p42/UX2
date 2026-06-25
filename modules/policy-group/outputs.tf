output "policy_id" {
  description = "ID of the centralized topology policy; consumed by each site stack via terraform_remote_state"
  value       = sdwan_centralized_policy.this.id
}

output "config_group_id" {
  value = null
}

output "device_ids" {
  value = []
}
