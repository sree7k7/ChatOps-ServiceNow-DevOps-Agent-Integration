import json
import hmac
import hashlib
import datetime
import urllib3
import base64
import logging
import boto3
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)
http = urllib3.PoolManager()

def lambda_handler(event, context):
    try:
        # Retrieve secrets
        secret_arn = os.environ['SECRET_ARN']
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=secret_arn)
        secrets = json.loads(response['SecretString'])
        WEBHOOK_URL = secrets['webhook_url']
        SECRET_STRING = secrets['secret_string']

        # Log the retrieved configuration to confirm Secrets Manager integration
        logger.info(f"Configuration loaded. Webhook URL: {WEBHOOK_URL}")

    except Exception as e:
        logger.error(f"Secret retrieval failed: {str(e)}")
        raise e

    # Handle SQS Records or Direct Invocation
    if 'Records' in event:
        # SQS Batch
        for record in event['Records']:-
            try:
                payload = json.loads(record['body'])
                process_incident(payload, WEBHOOK_URL, SECRET_STRING)
            except Exception as e:
                logger.error(f"Error processing record: {str(e)}")
        return {'statusCode': 200, 'body': "Batch processed"}
    else:
        # Direct Invocation (API Gateway or Test)
        try:
            if 'body' in event:
                body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
            else:
                body = event
            process_incident(body, WEBHOOK_URL, SECRET_STRING)
            return {'statusCode': 200, 'body': "Success"}
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            return {'statusCode': 500, 'body': str(e)}

def process_incident(body, WEBHOOK_URL, SECRET_STRING):
    try:
        inc_data = body.get('incident', body)
        inc_id = inc_data.get('number', 'UNKNOWN')
        
        # --- SMART LOGIC ---
        event_type = body.get('event_type', 'incident_created')
        
        # Default to 'created'
        aws_action = "created" 
        
        # Explicitly handle Resolution
        if "resolve" in event_type or "close" in event_type:
            aws_action = "resolved"
            logger.info(f"Resolving Incident: {inc_id}")
        
        # Priority Mapping
        p_val = str(inc_data.get('priority', '3'))
        if '1' in p_val: priority = 'CRITICAL'
        elif '2' in p_val: priority = 'HIGH'
        else: priority = 'MEDIUM'

        # Payload
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        agent_payload = {
            "eventType": "incident",
            "incidentId": str(inc_id),
            "title": f"[{inc_id}] {inc_data.get('short_description', '')}",
            "action": aws_action,
            "priority": priority,
            "description": inc_data.get('description', ''),
            "timestamp": timestamp
        }

        # Sign & Send
        payload_str = json.dumps(agent_payload, separators=(',', ':'))
        string_to_sign = f"{timestamp}:{payload_str}"
        
        signature_bytes = hmac.new(SECRET_STRING.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature_bytes).decode('utf-8')

        headers = {
            "Content-Type": "application/json",
            "x-amzn-event-signature": signature_b64,
            "x-amzn-event-timestamp": timestamp
        }

        response = http.request('POST', WEBHOOK_URL, body=payload_str, headers=headers)
        
        if response.status < 200 or response.status >= 300:
            raise Exception(f"AWS Webhook returned error: {response.status} - {response.data.decode('utf-8')}")
            
        logger.info(f"Sent to AWS: {response.status}")
    except Exception as e:
        logger.error(f"Logic Error: {str(e)}")
        raise e