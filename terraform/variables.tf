variable "aws_region" {
  description = "AWS region for SSM/IAM/Route 53"
  type        = string
  default     = "us-east-1"
}

# --- gateway configuration (written to SSM, read by the gateway at startup) ---

variable "rate_limit_per_min" {
  description = "Per-IP request rate limit on /api/chat"
  type        = number
  default     = 6
}

variable "max_queue_depth" {
  description = "Requests queued before load-shedding with 503s"
  type        = number
  default     = 8
}

variable "queue_timeout_s" {
  description = "Seconds a request may wait for the inference lock"
  type        = number
  default     = 90
}

variable "require_auth" {
  description = "If true the gateway enforces the bearer token; false = public demo"
  type        = bool
  default     = false
}

# --- DNS (optional) ------------------------------------------------------------

variable "domain_name" {
  description = "Apex domain for the demo (empty string skips DNS + bastion)"
  type        = string
  default     = "mini-agent.dev"
}

variable "use_packer_bastion_ami" {
  description = "Use the newest self-owned miniai-bastion-* AMI built by Packer instead of Canonical's stock Ubuntu AMI"
  type        = bool
  default     = false
}
