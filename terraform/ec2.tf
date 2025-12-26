# EBS Volume dedicated to repository storage
# This volume persists across container restarts and EC2 reboots

resource "aws_ebs_volume" "repos" {
  availability_zone = var.availability_zone
  size              = var.repos_volume_size
  type              = "gp3"

  tags = {
    Name        = "turbowrap-repos"
    Purpose     = "Repository storage"
    Application = "TurboWrap"
  }
}

# Attach the volume to the existing EC2 instance
resource "aws_volume_attachment" "repos_attach" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.repos.id
  instance_id = var.ec2_instance_id

  # Don't force detach if in use (safer)
  force_detach = false
}
