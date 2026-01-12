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

        ## create API Gateway to send message to receiver Lambda
        api = apigateway.RestApi(
            self, "SlackToServiceNowDevOpsAgentIntegrationAPI",
            rest_api_name="SlackToServiceNowDevOpsAgentIntegrationAPI",
            description="API Gateway to receive Slack events and send to ServiceNow via lambda",
            deploy_options=apigateway.StageOptions(
                stage_name="default",
                tracing_enabled=True,
                logging_level=apigateway.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                metrics_enabled=True,
                access_log_destination=apigateway.LogGroupLogDestination(api_gateway_log_group),
                access_log_format=apigateway.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True
                )
            )
        )

        ## secrets manager
        secret = secretsmanager.Secret(
            self, "SlackToSnowBotSecret",
            secret_name="SlackToSnowBotSecret",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({
                    "slack_signing_secret": "YOUR_SLACK_SECRET_HERE",
                    "sn_instance": "dev282699",
                    "sn_user": "admin",
                    "sn_pass": "YOUR_SN_PASSWORD_HERE"
                }),
                generate_string_key="dummy"
            )
        )

        ## receiver middleware lambda
        receiver_lambda = _lambda.Function(
            self, "SlackTosnow_api_to_receiver_lambda",
            function_name="SlackTosnow_api_to_receiver_lambda",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="slackToSnowBotViaAgent.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            memory_size=512,
            environment={
                "SECRET_ARN": secret.secret_arn
            }
        )

        secret.grant_read(receiver_lambda)

        ## intergration between api gateway and receiver lambda. api_gateway -> receiver_lambda
        ## api gateway will send the request to receiver lambda
        apigw_lambda_integration = apigateway.LambdaIntegration(
            receiver_lambda,
            proxy=True
        )

        # Attach the integration to a resource and method, allowing POST requests.
        # This line adds a new resource path "/apiGateway_receiver_middleware" to the API Gateway.
        # It then associates a POST method with this resource.
        # The POST method is configured to use the previously defined `integration` (which sends messages to SQS).
        # Finally, it specifies that the method should respond with a 200 status code upon successful execution.

        api.root.add_resource("apiGateway_receiver_middleware").add_method(
            "POST",
            apigw_lambda_integration,
            method_responses=[apigateway.MethodResponse(status_code="200")]
        )