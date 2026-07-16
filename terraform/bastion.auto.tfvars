# The first immutable ARM64 edge image was built by Packer on 2026-07-16.
# Terraform selects the newest available self-owned miniai-bastion-* AMI.
use_packer_bastion_ami = true

# This is intentionally public material. Keeping it in the tracked operator
# inputs preserves the break-glass EC2 key pair across bastion replacements;
# the matching private key stays only on the Mac mini.
ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH0ukVSkE0i7spVYDAVIFUfEpKfRuqw3EokTE+u1Gm1X cmurray@mac-mini"

# Runtime configuration, applied by cloud-init from SSM after the bastion is
# launched. This is not secret material.
acme_email = "cmurray1105@gmail.com"
