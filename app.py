#!/usr/bin/env python3
import aws_cdk as cdk
from chat_ops_service_now_dev_ops_agent_integration.service_now_dev_ops_agent_integration_stack import ChatOpsServiceNowDevOpsAgentIntegrationStack
from chat_ops_service_now_dev_ops_agent_integration.SlackToServiceNowBot_Lambda import slack_to_servicenow_devops_agent_integration


app = cdk.App()
ChatOpsServiceNowDevOpsAgentIntegrationStack(app, "ChatOpsServiceNowDevOpsAgentIntegrationStack",
    env=cdk.Environment(account='230150030147', region='us-east-1'),
)
slack_to_servicenow_devops_agent_integration(app, "SlackToServiceNowDevOpsAgentIntegrationStack",
    env=cdk.Environment(account='230150030147', region='us-east-1'),
)

app.synth()
