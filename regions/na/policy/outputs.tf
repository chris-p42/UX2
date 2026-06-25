output "policy_id" {
  description = "ID of the NA regional centralized policy; consumed by each NA site stack"
  value       = module.regional_policy.policy_id
}
