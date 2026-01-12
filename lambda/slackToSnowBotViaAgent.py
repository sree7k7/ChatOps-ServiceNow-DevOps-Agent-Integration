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
        SN_INSTANCE = secrets['sn_instance']
        SN_USER = secrets['sn_user']
        SN_PASS = secrets['sn_pass']

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
        logger.info(f"Received Command for: {command_text}")
        
        if not command_text.startswith("INC"):
            return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({"text": "❌ Invalid Ticket Number"})}

        # 4. QUERY SERVICENOW (Debug Added)
        sn_url = f"https://{SN_INSTANCE}.service-now.com/api/now/table/incident?sysparm_query=number={command_text}"
        auth_header = urllib3.make_headers(basic_auth=f"{SN_USER}:{SN_PASS}")
        
        logger.info(f"Querying ServiceNow: {sn_url}")
        find_req = http.request('GET', sn_url, headers=auth_header)
        
        # --- DEBUGGING BLOCK ---
        resp_body = find_req.data.decode('utf-8')
        logger.info(f"SN Status: {find_req.status}")
        logger.info(f"SN Response: {resp_body}")  # <--- CHECK CLOUDWATCH FOR THIS
        
        if find_req.status != 200:
            return {
                'statusCode': 200, 
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({"text": f"❌ ServiceNow Error {find_req.status}: Check Lambda Logs."})
            }
        # -----------------------

        find_data = json.loads(resp_body)
        
        if not find_data.get('result'):
            return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({"text": f"❌ Ticket {command_text} not found."})}
            
        sys_id = find_data['result'][0]['sys_id']
        
        # 5. UPDATE TICKET
        update_url = f"https://{SN_INSTANCE}.service-now.com/api/now/table/incident/{sys_id}"
        update_payload = {"state": "7", "close_code": "Solved (Work Around)", "close_notes": "Closed via Slack ChatOps"}
        
        update_req = http.request('PATCH', update_url, headers=auth_header, body=json.dumps(update_payload))
        
        if update_req.status == 200:
            return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({"response_type": "in_channel", "text": f"✅ **Success!** {command_text} Resolved."})}
        else:
            return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({"text": f"⚠️ Update failed: {update_req.status}"})}

    except Exception as e:
        logger.error(f"CRITICAL ERROR: {str(e)}")
        return {'statusCode': 200, 'body': json.dumps({"text": f"Error: {str(e)} check logs"})}