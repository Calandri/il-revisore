output "repos_volume_id" {
  description = "ID of the EBS volume for repositories"
  value       = aws_ebs_volume.repos.id
}

output "repos_volume_device" {
  description = "Device name where the volume is attached"
  value       = aws_volume_attachment.repos_attach.device_name
}

output "repos_volume_size" {
  description = "Size of the EBS volume in GB"
  value       = aws_ebs_volume.repos.size
}
