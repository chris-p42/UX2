output "policy_id" {
  description = "ID of the EMEA regional centralized policy; consumed by each EMEA site stack"
  value       = module.regional_policy.policy_id
}
