variable "aws_region" {
  description = "AWS region"
  default     = "eu-west-3"
}

variable "ec2_instance_id" {
  description = "Existing EC2 instance ID to attach the volume to"
  default     = "i-02cac4811086c1f92"
}

variable "repos_volume_size" {
  description = "Size of the EBS volume for repositories (GB)"
  default     = 12
}

variable "availability_zone" {
  description = "Availability zone (must match EC2 instance)"
  default     = "eu-west-3b" # Verified: EC2 is in eu-west-3b (Paris)
}
