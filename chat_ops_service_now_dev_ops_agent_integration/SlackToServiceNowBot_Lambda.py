import json
from aws_cdk import (
    # Duration,
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_event_sources,
    aws_sqs as sqs,
    aws_secretsmanager as secretsmanager,
    aws_apigateway as apigateway,
    aws_logs as logs
)
from constructs import Construct

class slack_to_servicenow_devops_agent_integration(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        ## Phase 1: Create IAM Role for API Gateway
        api_gateway_role = iam.Role(
            self, "ApiGatewayToSQSRole",
            assumed_by=iam.ServicePrincipal("apigateway.amazonaws.com"),
            description="Role for API Gateway to send messages to SQS"
        )

        ## log group for api gateway
        api_gateway_log_group = logs.LogGroup(
            self, "ApiGatewayLogGroup",
            retention=logs.RetentionDays.ONE_DAY,
            removal_policy=RemovalPolicy.DESTROY,
            log_group_name="/aws/apigateway_slack/ApiGatewayToSQSRole"
        )

        # Create IAM Role for API Gateway CloudWatch Logging
        api_gateway_log_role = iam.Role(
            self, "ApiGatewayCloudWatchLogRole",
            assumed_by=iam.ServicePrincipal("apigateway.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonAPIGatewayPushToCloudWatchLogs")
            ],
        )