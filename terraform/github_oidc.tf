# GitHub Actions authenticates with short-lived OIDC tokens rather than an AWS
# access key stored in the repository. The trust policy is intentionally bound
# to the `infrastructure` GitHub Environment, which is the only environment
# allowed to build an account-owned AMI.

resource "aws_iam_openid_connect_provider" "github_actions" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  tags           = { Name = "github-actions" }
}

data "aws_iam_policy_document" "github_actions_packer_trust" {
  statement {
    sid     = "GitHubActionsFromInfrastructureEnvironment"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # GitHub's environment subject form prevents a normal branch workflow,
    # fork, or another repository from assuming this role.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:cmurray1105/miniAI:environment:infrastructure"]
    }
  }
}

resource "aws_iam_role" "github_packer" {
  name                 = "miniai-github-packer"
  description          = "GitHub Actions OIDC role for building miniAI bastion AMIs"
  max_session_duration = 3600
  assume_role_policy   = data.aws_iam_policy_document.github_actions_packer_trust.json
}

# Packer's amazon-ebs builder creates temporary EC2 infrastructure (an
# instance, security group, key pair, and EBS snapshots) before registering an
# AMI. These APIs do not support a practical resource-level restriction, so the
# role is constrained at the identity boundary above and grants only that
# builder's required EC2 actions.
data "aws_iam_policy_document" "github_packer" {
  statement {
    sid = "BuildAndRegisterBastionAmi"
    actions = [
      "ec2:AttachVolume",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:CopyImage",
      "ec2:CreateImage",
      "ec2:CreateKeyPair",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSnapshot",
      "ec2:CreateTags",
      "ec2:CreateVolume",
      "ec2:DeleteKeyPair",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSnapshot",
      "ec2:DeleteVolume",
      "ec2:DeregisterImage",
      "ec2:DescribeImageAttribute",
      "ec2:DescribeImages",
      "ec2:DescribeInstanceStatus",
      "ec2:DescribeInstanceTypeOfferings",
      "ec2:DescribeInstances",
      "ec2:DescribeRegions",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSnapshots",
      "ec2:DescribeSubnets",
      "ec2:DescribeTags",
      "ec2:DescribeVolumes",
      "ec2:DescribeVpcs",
      "ec2:DetachVolume",
      "ec2:GetPasswordData",
      "ec2:ModifyImageAttribute",
      "ec2:ModifyInstanceAttribute",
      "ec2:ModifySnapshotAttribute",
      "ec2:RegisterImage",
      "ec2:RunInstances",
      "ec2:StopInstances",
      "ec2:TerminateInstances",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_packer" {
  name   = "miniai-github-packer-ec2"
  role   = aws_iam_role.github_packer.id
  policy = data.aws_iam_policy_document.github_packer.json
}
