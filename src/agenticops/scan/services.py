"""AWS Service definitions for scanning."""

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class AWSServiceDef:
    """Definition of an AWS service for scanning."""

    name: str
    boto3_service: str
    description: str
    list_method: str
    list_key: str  # Key in response that contains the resource list
    id_field: str  # Field name for resource ID
    name_field: Optional[str] = None
    arn_field: Optional[str] = None
    status_field: Optional[str] = None
    cloudwatch_namespace: Optional[str] = None
    default_metrics: list[str] = field(default_factory=list)


# Supported AWS services for MVP
AWS_SERVICES: dict[str, AWSServiceDef] = {
    "EC2": AWSServiceDef(
        name="EC2",
        boto3_service="ec2",
        description="Elastic Compute Cloud instances",
        list_method="describe_instances",
        list_key="Reservations",
        id_field="InstanceId",
        name_field="Tags",  # Need to extract from tags
        status_field="State.Name",
        cloudwatch_namespace="AWS/EC2",
        default_metrics=["CPUUtilization", "NetworkIn", "NetworkOut", "DiskReadOps", "DiskWriteOps"],
    ),
    "Lambda": AWSServiceDef(
        name="Lambda",
        boto3_service="lambda",
        description="Lambda functions",
        list_method="list_functions",
        list_key="Functions",
        id_field="FunctionName",
        name_field="FunctionName",
        arn_field="FunctionArn",
        cloudwatch_namespace="AWS/Lambda",
        default_metrics=["Invocations", "Duration", "Errors", "Throttles", "ConcurrentExecutions"],
    ),
    "RDS": AWSServiceDef(
        name="RDS",
        boto3_service="rds",
        description="Relational Database Service instances",
        list_method="describe_db_instances",
        list_key="DBInstances",
        id_field="DBInstanceIdentifier",
        name_field="DBInstanceIdentifier",
        arn_field="DBInstanceArn",
        status_field="DBInstanceStatus",
        cloudwatch_namespace="AWS/RDS",
        default_metrics=[
            "CPUUtilization",
            "DatabaseConnections",
            "FreeStorageSpace",
            "ReadIOPS",
            "WriteIOPS",
        ],
    ),
    "S3": AWSServiceDef(
        name="S3",
        boto3_service="s3",
        description="Simple Storage Service buckets",
        list_method="list_buckets",
        list_key="Buckets",
        id_field="Name",
        name_field="Name",
        cloudwatch_namespace="AWS/S3",
        default_metrics=["BucketSizeBytes", "NumberOfObjects"],
    ),
    "ECS": AWSServiceDef(
        name="ECS",
        boto3_service="ecs",
        description="Elastic Container Service clusters",
        list_method="list_clusters",
        list_key="clusterArns",
        id_field="clusterArn",
        arn_field="clusterArn",
        cloudwatch_namespace="AWS/ECS",
        default_metrics=["CPUUtilization", "MemoryUtilization"],
    ),
    "EKS": AWSServiceDef(
        name="EKS",
        boto3_service="eks",
        description="Elastic Kubernetes Service clusters",
        list_method="list_clusters",
        list_key="clusters",
        id_field="name",
        name_field="name",
        cloudwatch_namespace="AWS/EKS",
        default_metrics=[],
    ),
    "DynamoDB": AWSServiceDef(
        name="DynamoDB",
        boto3_service="dynamodb",
        description="DynamoDB tables",
        list_method="list_tables",
        list_key="TableNames",
        id_field="TableName",
        name_field="TableName",
        cloudwatch_namespace="AWS/DynamoDB",
        default_metrics=[
            "ConsumedReadCapacityUnits",
            "ConsumedWriteCapacityUnits",
            "ThrottledRequests",
        ],
    ),
    "SQS": AWSServiceDef(
        name="SQS",
        boto3_service="sqs",
        description="Simple Queue Service queues",
        list_method="list_queues",
        list_key="QueueUrls",
        id_field="QueueUrl",
        cloudwatch_namespace="AWS/SQS",
        default_metrics=[
            "NumberOfMessagesReceived",
            "NumberOfMessagesSent",
            "ApproximateNumberOfMessagesVisible",
        ],
    ),
    "SNS": AWSServiceDef(
        name="SNS",
        boto3_service="sns",
        description="Simple Notification Service topics",
        list_method="list_topics",
        list_key="Topics",
        id_field="TopicArn",
        arn_field="TopicArn",
        cloudwatch_namespace="AWS/SNS",
        default_metrics=["NumberOfMessagesPublished", "NumberOfNotificationsDelivered"],
    ),
    "ElastiCache": AWSServiceDef(
        name="ElastiCache",
        boto3_service="elasticache",
        description="ElastiCache clusters",
        list_method="describe_cache_clusters",
        list_key="CacheClusters",
        id_field="CacheClusterId",
        name_field="CacheClusterId",
        arn_field="ARN",
        status_field="CacheClusterStatus",
        cloudwatch_namespace="AWS/ElastiCache",
        default_metrics=["CPUUtilization", "CurrConnections", "CacheHits", "CacheMisses"],
    ),
    "CloudFront": AWSServiceDef(
        name="CloudFront",
        boto3_service="cloudfront",
        description="CloudFront distributions",
        list_method="list_distributions",
        list_key="DistributionList.Items",
        id_field="Id",
        arn_field="ARN",
        status_field="Status",
        cloudwatch_namespace="AWS/CloudFront",
        default_metrics=["Requests", "BytesDownloaded", "4xxErrorRate", "5xxErrorRate"],
    ),
    "APIGateway": AWSServiceDef(
        name="APIGateway",
        boto3_service="apigateway",
        description="API Gateway REST APIs",
        list_method="get_rest_apis",
        list_key="items",
        id_field="id",
        name_field="name",
        cloudwatch_namespace="AWS/ApiGateway",
        default_metrics=["Count", "Latency", "4XXError", "5XXError"],
    ),
    "StepFunctions": AWSServiceDef(
        name="StepFunctions",
        boto3_service="stepfunctions",
        description="Step Functions state machines",
        list_method="list_state_machines",
        list_key="stateMachines",
        id_field="stateMachineArn",
        name_field="name",
        arn_field="stateMachineArn",
        cloudwatch_namespace="AWS/States",
        default_metrics=["ExecutionsStarted", "ExecutionsFailed", "ExecutionsSucceeded"],
    ),
    "Kinesis": AWSServiceDef(
        name="Kinesis",
        boto3_service="kinesis",
        description="Kinesis data streams",
        list_method="list_streams",
        list_key="StreamNames",
        id_field="StreamName",
        name_field="StreamName",
        cloudwatch_namespace="AWS/Kinesis",
        default_metrics=["IncomingRecords", "IncomingBytes", "GetRecords.Success"],
    ),
    "Redshift": AWSServiceDef(
        name="Redshift",
        boto3_service="redshift",
        description="Redshift clusters",
        list_method="describe_clusters",
        list_key="Clusters",
        id_field="ClusterIdentifier",
        name_field="ClusterIdentifier",
        status_field="ClusterStatus",
        cloudwatch_namespace="AWS/Redshift",
        default_metrics=["CPUUtilization", "DatabaseConnections", "PercentageDiskSpaceUsed"],
    ),
    # -----------------------------------------------------------------------
    # VPC / Networking
    # -----------------------------------------------------------------------
    "VPC": AWSServiceDef(
        name="VPC",
        boto3_service="ec2",
        description="Virtual Private Clouds",
        list_method="describe_vpcs",
        list_key="Vpcs",
        id_field="VpcId",
        name_field="Tags",
        status_field="State",
        cloudwatch_namespace="AWS/VPC",
        default_metrics=[],
    ),
    "Subnet": AWSServiceDef(
        name="Subnet",
        boto3_service="ec2",
        description="VPC Subnets",
        list_method="describe_subnets",
        list_key="Subnets",
        id_field="SubnetId",
        name_field="Tags",
        status_field="State",
    ),
    "SecurityGroup": AWSServiceDef(
        name="SecurityGroup",
        boto3_service="ec2",
        description="VPC Security Groups",
        list_method="describe_security_groups",
        list_key="SecurityGroups",
        id_field="GroupId",
        name_field="GroupName",
    ),
    "NATGateway": AWSServiceDef(
        name="NATGateway",
        boto3_service="ec2",
        description="NAT Gateways",
        list_method="describe_nat_gateways",
        list_key="NatGateways",
        id_field="NatGatewayId",
        status_field="State",
        cloudwatch_namespace="AWS/NATGateway",
        default_metrics=[
            "ActiveConnectionCount",
            "BytesInFromDestination",
            "BytesOutToDestination",
            "ErrorPortAllocation",
            "PacketsDropCount",
        ],
    ),
    "TransitGateway": AWSServiceDef(
        name="TransitGateway",
        boto3_service="ec2",
        description="Transit Gateways",
        list_method="describe_transit_gateways",
        list_key="TransitGateways",
        id_field="TransitGatewayId",
        status_field="State",
        cloudwatch_namespace="AWS/TransitGateway",
        default_metrics=[
            "BytesIn",
            "BytesOut",
            "PacketsIn",
            "PacketsOut",
            "PacketDropCountBlackhole",
        ],
    ),
    "ELB": AWSServiceDef(
        name="ELB",
        boto3_service="elbv2",
        description="Application/Network Load Balancers",
        list_method="describe_load_balancers",
        list_key="LoadBalancers",
        id_field="LoadBalancerArn",
        name_field="LoadBalancerName",
        arn_field="LoadBalancerArn",
        status_field="State.Code",
        cloudwatch_namespace="AWS/ApplicationELB",
        default_metrics=[
            "RequestCount",
            "TargetResponseTime",
            "HTTPCode_ELB_5XX_Count",
            "UnHealthyHostCount",
            "HealthyHostCount",
        ],
    ),
    "RouteTable": AWSServiceDef(
        name="RouteTable",
        boto3_service="ec2",
        description="VPC Route Tables",
        list_method="describe_route_tables",
        list_key="RouteTables",
        id_field="RouteTableId",
    ),
}


def get_supported_services() -> list[str]:
    """Get list of supported AWS service names."""
    return list(AWS_SERVICES.keys())


def get_service_def(service_name: str) -> Optional[AWSServiceDef]:
    """Get service definition by name."""
    return AWS_SERVICES.get(service_name)


# Re-export from regions module for backward compatibility
from agenticops.scan.regions import (
    get_all_regions,
    get_common_regions,
    get_region_name,
    validate_region,
)
