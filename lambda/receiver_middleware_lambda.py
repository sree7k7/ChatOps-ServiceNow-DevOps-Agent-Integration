import json
import hmac
import hashlib
import urllib3
import time
import base64
import logging
from urllib.parse import parse_qs
import boto3
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)
http = urllib3.PoolManager()

def verify_slack_signature(headers, body, secret):
    timestamp = headers.get('x-slack-request-timestamp', '')
    signature = headers.get('x-slack-signature', '')
    if not timestamp or abs(time.time() - int(timestamp)) > 60 * 5:
        return False
    sig_basestring = f"v0:{timestamp}:{body}".encode('utf-8')
    my_signature = "v0=" + hmac.new(secret.encode('utf-8'), sig_basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(my_signature, signature)

def lambda_handler(event, context):
    try:
        # Retrieve secrets
        secret_arn = os.environ['SECRET_ARN']
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=secret_arn)
        secrets = json.loads(response['SecretString'])
        
        SLACK_SIGNING_SECRET = secrets['slack_signing_secret']

        # 1. Parse Slack Input
        headers = {k.lower(): v for k, v in event['headers'].items()}
        raw_body = event.get('body', '')
        if event.get('isBase64Encoded'):
            raw_body = base64.b64decode(raw_body).decode('utf-8')

        # 2. Verify Signature
        if not verify_slack_signature(headers, raw_body, SLACK_SIGNING_SECRET):
            logger.error("Signature verification failed")
            return {'statusCode': 401, 'body': "Invalid Signature"}

        # 3. Extract Ticket Number
        params = parse_qs(raw_body)
        command_text = params.get('text', [''])[0].strip()
        response_url = params.get('response_url', [''])[0]
        user_id = params.get('user_id', [''])[0]

        logger.info(f"Received Command for: {command_text}")
        
        if not command_text.startswith("INC"):
            return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({"text": "❌ Invalid Ticket Number"})}

        # 4. SEND TO SQS (Async Processing)
        sqs = boto3.client('sqs')
        queue_url = os.environ['SQS_QUEUE_URL']
        
        message_payload = {
            "ticket_number": command_text,
            "response_url": response_url,
            "user_id": user_id
        }
        
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message_payload))

        # 5. Immediate Response to Slack
        return {
            'statusCode': 200, 
            'headers': {'Content-Type': 'application/json'}, 
            'body': json.dumps({"text": f"⏳ Received request for {command_text}. Processing..."})
        }

    except Exception as e:
        logger.error(f"CRITICAL ERROR: {str(e)}")
        return {'statusCode': 200, 'body': json.dumps({"text": f"Error: {str(e)} check logs"})}