resource "sdwan_configuration_group" "this" {
  name        = "cfg-grp-${var.site_name}"
  description = "Configuration group for ${var.site_name}"
  solution    = "sdwan"

  feature_profiles = concat(
    [
      { id = var.system_profile_id },
      { id = var.transport_profile_id },
      { id = var.service_profile_id },
    ],
    var.cli_profile_id != null ? [{ id = var.cli_profile_id }] : []
  )
}
