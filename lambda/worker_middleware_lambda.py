import json
import urllib3
import boto3
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)
http = urllib3.PoolManager()

def lambda_handler(event, context):
    # Retrieve secrets
    try:
        secret_arn = os.environ['SECRET_ARN']
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=secret_arn)
        secrets = json.loads(response['SecretString'])
        
        SN_INSTANCE = secrets['sn_instance']
        SN_USER = secrets['sn_user']
        SN_PASS = secrets['sn_pass']
    except Exception as e:
        logger.error(f"Failed to retrieve secrets: {str(e)}")
        raise e

    # Process SQS Records
    for record in event['Records']:
        try:
            payload = json.loads(record['body'])
            process_message(payload, SN_INSTANCE, SN_USER, SN_PASS)
        except Exception as e:
            logger.error(f"Error processing record: {str(e)}")
            continue
            
    return {'statusCode': 200, 'body': "Processed"}

def process_message(payload, sn_instance, sn_user, sn_pass):
    ticket_number = payload.get('ticket_number')
    response_url = payload.get('response_url')
    
    if not ticket_number or not response_url:
        logger.error("Missing ticket_number or response_url in payload")
        return

    auth_header = urllib3.make_headers(basic_auth=f"{sn_user}:{sn_pass}")
    headers = {'Content-Type': 'application/json'}
    headers.update(auth_header)

    # 1. Query ServiceNow to get sys_id
    sn_url = f"https://{sn_instance}.service-now.com/api/now/table/incident?sysparm_query=number={ticket_number}"
    
    try:
        logger.info(f"Querying ServiceNow for {ticket_number}")
        find_req = http.request('GET', sn_url, headers=headers)
        
        if find_req.status != 200:
            logger.error(f"ServiceNow query failed: {find_req.status}")
            send_slack_response(response_url, f"❌ ServiceNow Error {find_req.status} while searching for ticket.")
            return

        find_data = json.loads(find_req.data.decode('utf-8'))
        
        if not find_data.get('result'):
            logger.info(f"Ticket {ticket_number} not found")
            send_slack_response(response_url, f"❌ Ticket {ticket_number} not found.")
            return
            
        sys_id = find_data['result'][0]['sys_id']
        
        # 2. Update Ticket
        update_url = f"https://{sn_instance}.service-now.com/api/now/table/incident/{sys_id}"
        update_payload = {
            "state": "7", 
            "close_code": "Solved (Work Around)", 
            "close_notes": "Closed via Slack ChatOps (Async Worker)"
        }
        
        logger.info(f"Updating ticket {ticket_number} (sys_id: {sys_id})")
        update_req = http.request('PATCH', update_url, headers=headers, body=json.dumps(update_payload))
        
        if update_req.status == 200:
            logger.info(f"Successfully updated {ticket_number}")
            send_slack_response(response_url, f"✅ **Success!** {ticket_number} has been resolved.")
        else:
            logger.error(f"Update failed: {update_req.status}")
            send_slack_response(response_url, f"⚠️ Update failed for {ticket_number}. Status: {update_req.status}")

    except Exception as e:
        logger.error(f"Exception calling ServiceNow: {str(e)}")
        send_slack_response(response_url, f"❌ Internal Error processing {ticket_number}.")

def send_slack_response(response_url, text):
    message = {
        "response_type": "in_channel",
        "text": text
    }
    try:
        http.request('POST', response_url, body=json.dumps(message), headers={'Content-Type': 'application/json'})
    except Exception as e:
        logger.error(f"Failed to send Slack response: {str(e)}")