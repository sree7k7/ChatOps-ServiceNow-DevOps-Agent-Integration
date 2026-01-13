import json
import urllib3
import boto3
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)
http = urllib3.PoolManager()

SECRETS_CLIENT = boto3.client('secretsmanager')

def lambda_handler(event, context):
    try:
        secret_arn = os.environ['SECRET_ARN']
        response = SECRETS_CLIENT.get_secret_value(SecretId=secret_arn)
        secrets = json.loads(response['SecretString'])
        
        SN_INSTANCE = secrets['sn_instance']
        SN_USER = secrets['sn_user']
        SN_PASS = secrets['sn_pass']
    except Exception as e:
        logger.error(f"Failed to retrieve secrets: {str(e)}")
        raise e 

    for record in event['Records']:
        try:
            payload = json.loads(record['body'])
            process_message(payload, SN_INSTANCE, SN_USER, SN_PASS)
        except Exception as e:
            logger.error(f"Error processing record: {str(e)}")
            raise e 
            
    return {'statusCode': 200, 'body': "Batch Processed"}

def process_message(payload, sn_instance, sn_user, sn_pass):
    action = payload.get('action') # /ops-resolve or /ops-status
    ticket_number = payload.get('ticket_number')
    response_url = payload.get('response_url')
    
    if not ticket_number or not response_url:
        return

    auth_header = urllib3.make_headers(basic_auth=f"{sn_user}:{sn_pass}")
    headers = {'Content-Type': 'application/json'}
    headers.update(auth_header)

    # 1. GET TICKET DETAILS (Common for both actions)
    sn_url = f"https://{sn_instance}.service-now.com/api/now/table/incident?sysparm_query=number={ticket_number}&sysparm_display_value=true"
    
    logger.info(f"Querying ServiceNow for {ticket_number}")
    find_req = http.request('GET', sn_url, headers=headers)
    
    if find_req.status != 200:
        raise Exception(f"ServiceNow query failed: {find_req.status}")

    find_data = json.loads(find_req.data.decode('utf-8'))
    
    if not find_data.get('result'):
        send_slack_response(response_url, f"❌ Ticket {ticket_number} not found.")
        return
        
    incident = find_data['result'][0]
    sys_id = incident['sys_id']
    current_state = incident['state'] # e.g., "New", "Resolved"
    short_desc = incident['short_description']

    # --- LOGIC BRANCH ---
    
    # CASE A: STATUS CHECK
    if action == '/ops-status':
        msg = f"📋 *Status Report for {ticket_number}*\n> **State:** {current_state}\n> **Summary:** {short_desc}"
        send_slack_response(response_url, msg)
        return

    # CASE B: RESOLVE TICKET
    elif action == '/ops-resolve':
        if current_state in ['Resolved', 'Closed']:
            send_slack_response(response_url, f"⚠️ {ticket_number} is already *{current_state}*.")
            return

        update_url = f"https://{sn_instance}.service-now.com/api/now/table/incident/{sys_id}"
        # state '7' = Closed in standard SN instances (check your instance mapping)
        update_payload = {"state": "7", "close_code": "Solved (Work Around)", "close_notes": "Closed via Slack"}
        
        update_req = http.request('PATCH', update_url, headers=headers, body=json.dumps(update_payload))
        
        if update_req.status == 200:
            send_slack_response(response_url, f"✅ **Success!** {ticket_number} has been resolved.")
        else:
            raise Exception(f"Update failed: {update_req.status}")

def send_slack_response(response_url, text):
    try:
        http.request('POST', response_url, body=json.dumps({"text": text, "response_type": "in_channel"}), headers={'Content-Type': 'application/json'})
    except Exception as e:
        logger.error(f"Failed to send Slack response: {str(e)}")