"""Ten rows of the cloud CLI's read-only table: what the diagnosis and the plan agent really read (MVP-2.9.0 N30).

Since N30 these two agents can send only what the code calls a read. Measured on a copy of the local database (two
months, about 105 diagnoses and 71 plans): through the account-bound tool they had run 31 commands the table did not
know — 17 describe-, 6 list-, 6 get-, 2 generate-credential-report; not one of them a change. The describe- / list-
operations of the services they asked are added row by row. It is NOT a rule by verb: `aws --no-p lambda invoke …
list-out.json` reads as a «list-» operation to anything that looks for the verb, and such a rule would also reach the
auto-approval floor and the read-only account.
"""
import pytest

from agenticops.tools.aws_cli_tool import READONLY_PREFIXES, _classify_command

NEW_ROWS = ["aws kafka describe-", "aws kafka list-", "aws configservice describe-", "aws configservice list-",
            "aws s3control describe-", "aws s3control list-", "aws osis list-", "aws emr-serverless list-",
            "aws bedrock-agentcore-control list-", "aws efs describe-"]


def test_the_ten_rows_are_in_the_table_once():
    for row in NEW_ROWS:
        assert READONLY_PREFIXES.count(row) == 1, row
    assert len(READONLY_PREFIXES) == len(set(READONLY_PREFIXES))


@pytest.mark.parametrize("command", [
    "aws kafka describe-cluster --cluster-arn x", "aws kafka list-clusters", "aws kafka list-nodes --cluster-arn x",
    "aws configservice describe-config-rules", "aws configservice describe-compliance-by-config-rule",
    "aws configservice list-discovered-resources --resource-type AWS::EC2::Instance",
    "aws s3control describe-job --account-id 1 --job-id j", "aws s3control list-access-points --account-id 1",
    "aws osis list-pipelines", "aws emr-serverless list-applications", "aws emr-serverless list-job-runs --application-id x",
    "aws bedrock-agentcore-control list-agent-runtimes",
    "aws efs describe-file-systems --region us-east-1 --output json", "aws efs describe-mount-targets --file-system-id fs-1",
    "aws kafka 'list-clusters'", "aws  kafka   list-clusters",                 # judged as the tool will run it
])
def test_a_describe_or_a_list_of_these_services_is_a_read(command):
    assert _classify_command(command) == "readonly"


@pytest.mark.parametrize("command,tier", [
    # the same services' other operations are what they were
    ("aws kafka get-bootstrap-brokers --cluster-arn x", "unknown"), ("aws kafka delete-cluster --cluster-arn x", "write"),
    ("aws kafka create-cluster --cluster-name x", "write"), ("aws kafka update-broker-count --cluster-arn x", "write"),
    ("aws kafka reboot-broker --cluster-arn x", "write"), ("aws kafka", "unknown"),
    ("aws configservice put-config-rule --config-rule file://x", "write"),
    ("aws configservice get-compliance-details-by-config-rule --config-rule-name x", "unknown"),
    ("aws configservice select-resource-config --expression x", "unknown"),
    ("aws configservice start-config-rules-evaluation", "write"),
    ("aws configservice delete-config-rule --config-rule-name x", "write"),
    ("aws s3control get-public-access-block --account-id 1", "unknown"),
    ("aws s3control put-public-access-block --account-id 1", "write"), ("aws s3control create-job --account-id 1", "write"),
    ("aws s3control delete-access-point --account-id 1 --name x", "write"),
    ("aws osis get-pipeline --pipeline-name x", "unknown"), ("aws osis describe-x", "unknown"),
    ("aws osis create-pipeline --pipeline-name x", "write"), ("aws osis stop-pipeline --pipeline-name x", "write"),
    ("aws emr-serverless get-application --application-id x", "unknown"), ("aws emr-serverless describe-x", "unknown"),
    ("aws emr-serverless start-job-run --application-id x", "write"),
    ("aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id x", "unknown"),
    ("aws bedrock-agentcore-control describe-x", "unknown"),
    ("aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id x", "write"),
    ("aws efs create-file-system", "write"), ("aws efs delete-file-system --file-system-id fs-1", "write"),
    ("aws efs put-lifecycle-configuration --file-system-id fs-1", "write"),
    ("aws efs list-tags-for-resource --resource-id fs-1", "unknown"), ("aws efs", "unknown"),
    # a service whose name only begins like one of them
    ("aws kafkaconnect list-connectors", "unknown"), ("aws efs-x describe-file-systems", "unknown"),
    # the verb is not what is read: an abbreviated global option before another service's write
    ("aws --no-p lambda invoke --function-name f list-out.json", "unknown"),
    ("aws lambda invoke --function-name f describe-out.json", "write"),
    # … and what the two agents sent that is still no read
    ("aws iam generate-credential-report", "unknown"),
])
def test_everything_else_is_what_it_was(command, tier):
    assert _classify_command(command) == tier


def test_the_scan_that_runs_every_hour_no_longer_fills_the_ledger():
    # 950 of the 1,728 ledger rows on the copy database were this one read, written as «unknown» by the scanner
    assert _classify_command("aws efs describe-file-systems --region eu-west-1 --output json") == "readonly"
