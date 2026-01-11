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

class ChatOpsServiceNowDevOpsAgentIntegrationStack(Stack):

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
            log_group_name="/aws/apigateway/ApiGatewayToSQSRole"
        )

        # Create IAM Role for API Gateway CloudWatch Logging.
        api_gateway_log_role = iam.Role(
            self, "ApiGatewayCloudWatchLogRole",
            assumed_by=iam.ServicePrincipal("apigateway.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonAPIGatewayPushToCloudWatchLogs")]
        )

        # Set the CloudWatch Role ARN for the API Gateway Account
        api_gateway_account = apigateway.CfnAccount(
            self, "ApiGatewayAccount",
            cloud_watch_role_arn=api_gateway_log_role.role_arn
        )

        ## Phase 2: Create SQS Queue
        queue = sqs.Queue(
            self, "ServiceNowDevOpsSQSQueue",
            queue_name="ServiceNow-DevOps-SQSQueue"
        )

        # Grant API Gateway role permission to send messages to the queue
        queue.grant_send_messages(api_gateway_role)

        ## secrets manager
        secret = secretsmanager.Secret(
            self, "ServiceNowDevOpsAgentSecret",
            secret_name="ServiceNowDevOpsAgentSecret",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({
                    "webhook_url": "placeholder_value",
                    "secret_string": "placeholder_value"
                }),
                generate_string_key="dummy"  # Dummy key to force generation
            )
        )

        ## add logs for lambda
        middleware_log_group = logs.LogGroup(
            self, "ServiceNowDevOpsMiddlemanLogGroup",
            retention=logs.RetentionDays.ONE_DAY,
            removal_policy=RemovalPolicy.DESTROY, 
            log_group_name="/aws/lambda/slack-to-servicenow-devops-middleman"
        )

        ## Lambda function for ServiceNow DevOps Middleware

        servicenow_devops_middleman_lambda = _lambda.Function(
            self, "ServiceNowDevOpsMiddlemanLambda",
            function_name="servicenow_devops_middleman_lambda",
            runtime=_lambda.Runtime.PYTHON_3_13,
            handler="servicenow-devops-middleman.lambda_handler",
            code=_lambda.Code.from_asset("lambda"),
            environment={
                "SECRET_ARN": secret.secret_arn
            },
            logging_format=_lambda.LoggingFormat.JSON,
            log_group=middleware_log_group,
            system_log_level_v2=_lambda.SystemLogLevel.INFO,
            application_log_level_v2=_lambda.ApplicationLogLevel.INFO,
        )
        secret.grant_read(servicenow_devops_middleman_lambda)


        ## Trigger lambda function using API Gateway when HTTP request is received
        ## REST API
        ## security is OPEN
        api = apigateway.RestApi(
            self, "SlackToServiceNowBotApi",
            rest_api_name="SlackToServiceNowBot-API",
            description="Created by AWS Lambda",
            api_key_source_type=apigateway.ApiKeySourceType.HEADER,
            endpoint_configuration=apigateway.EndpointConfiguration(
                types=[apigateway.EndpointType.REGIONAL]
            ),
            # disable_execute_api_endpoint=False,
            
            # Stage configuration
            deploy=True,
            deploy_options=apigateway.StageOptions(
                stage_name="default",
                tracing_enabled=True,
                data_trace_enabled=True,
                logging_level=apigateway.MethodLoggingLevel.INFO,
                access_log_destination=apigateway.LogGroupLogDestination(api_gateway_log_group),
                description="Created by AWS Lambda",
            )
            
        )
        api.node.add_dependency(api_gateway_account)

        ## Phase 3: Update API Gateway to integrate with SQS (Producer)
        integration = apigateway.AwsIntegration(
            service="sqs",
            path="{}/{}".format(Stack.of(self).account, queue.queue_name),
            integration_http_method="POST",
            options=apigateway.IntegrationOptions(
                credentials_role=api_gateway_role,
                request_parameters={
                    "integration.request.header.Content-Type": "'application/x-www-form-urlencoded'"
                },
                request_templates={
                    "application/json": "Action=SendMessage&MessageBody=$input.body"
                },
                integration_responses=[
                    apigateway.IntegrationResponse(status_code="200")
                ]
            )
        )

        # Attach the integration to a resource and method, allowing POST requests
        # explain this line: 
        # This line adds a new resource path "/servicenow_devops_middleman_lambda" to the API Gateway.
        # It then associates a POST method with this resource.
        # The POST method is configured to use the previously defined `integration` (which sends messages to SQS).
        # Finally, it specifies that the method should respond with a 200 status code upon successful execution.

        api.root.add_resource("servicenow_devops_middleman_lambda").add_method("POST", integration, method_responses=[apigateway.MethodResponse(status_code="200")])

        ## Phase 3: Configure Lambda to trigger from SQS (Consumer)
        servicenow_devops_middleman_lambda.add_event_source(lambda_event_sources.SqsEventSource(queue, batch_size=10))

        full_api_url = api.url + "servicenow_devops_middleman_lambda"

        # ServiceNow Business Rule Script Output
        sn_script = f"""copy the below code:
==========================================
(function executeRule(current, previous /*null when async*/) {{

    // --- RELIABLE TRIGGER ---
    // We send EVERYTHING to Lambda. 
    // The Lambda will decide what is important enough to forward to AWS.
    
    gs.info('=== AWS Middleware Triggered: ' + current.number + ' ===');

    try {{
        var lambdaUrl = '{full_api_url}';
        
        // Determine simplistic event type
        var evtType = "incident_updated";
        if (current.isNewRecord()) {{
            evtType = "incident_created";
        }} else if (current.getValue('state') == '6' || current.getValue('state') == '7') {{
            evtType = "incident_resolved";
        }}
        
        var payload = {{
            "event_type": evtType,
            "incident": {{
                "number": current.number.toString(),
                "sys_id": current.sys_id.toString(),
                "short_description": current.short_description.toString(),
                "description": (current.description || "").toString(),
                "priority": current.priority.toString(),
                "state": current.getValue('state'), // Send raw state value (e.g. "1", "7")
                "state_display": current.getDisplayValue('state') // Send readable name (e.g. "Resolved")
            }}
        }};
        
        var request = new sn_ws.RESTMessageV2();
        request.setEndpoint(lambdaUrl);
        request.setHttpMethod('POST');
        request.setRequestHeader('Content-Type', 'application/json');
        request.setRequestBody(JSON.stringify(payload));
        
        var response = request.execute();
        gs.info("AWS Sync Status: " + response.getStatusCode());

    }} catch (ex) {{
        gs.error("AWS Sync Error: " + ex.message);
    }}

}})(current, previous);
=================================================="""

        CfnOutput(self, "ServiceNowBusinessRule", 
            value=sn_script,
            description="Copy this script into your ServiceNow Business Rule")