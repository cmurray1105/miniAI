# Least-privilege identity for the Mac mini: it can read /miniai/* parameters
# and decrypt them via SSM. Nothing else in the account is reachable if the
# box is compromised.

data "aws_caller_identity" "current" {}

resource "aws_iam_user" "miniai_host" {
  name = "miniai-host"
}

data "aws_iam_policy_document" "ssm_read" {
  statement {
    sid = "ReadMiniaiParameters"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParametersByPath",
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/miniai/*",
    ]
  }

  statement {
    sid       = "DecryptViaSsmOnly"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:key/*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_user_policy" "miniai_ssm_read" {
  name   = "miniai-ssm-read"
  user   = aws_iam_user.miniai_host.name
  policy = data.aws_iam_policy_document.ssm_read.json
}

# Access key for the mini's ~/.aws/credentials (the unavoidable off-cloud
# bootstrap credential — see deploy/SECRETS.md for the honest discussion).
# Retrieve once with: terraform output -raw host_secret_access_key
resource "aws_iam_access_key" "miniai_host" {
  user = aws_iam_user.miniai_host.name
}
