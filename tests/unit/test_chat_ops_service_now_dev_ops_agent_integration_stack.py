import aws_cdk as core
import aws_cdk.assertions as assertions

from chat_ops_service_now_dev_ops_agent_integration.ServiceNowDevOpsMiddleware import ChatOpsServiceNowDevOpsAgentIntegrationStack

# example tests. To run these tests, uncomment this file along with the example
# resource in chat_ops_service_now_dev_ops_agent_integration/chat_ops_service_now_dev_ops_agent_integration_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = ChatOpsServiceNowDevOpsAgentIntegrationStack(app, "chat-ops-service-now-dev-ops-agent-integration")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
