import os
import json
import boto3
import logging
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

lambda_client = boto3.client("lambda")

SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
RAG_CHAIN_LAMBDA_NAME = os.getenv("RAG_CHAIN_LAMBDA_NAME")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
IGNORE_KEYWORDS = [
    # 해당 키워드들이 포함된 문의인 경우, 무시하도록
    # 체인 앞에 이러한 작업을 붙힐 수도 있겠지만, 이와 같은 키워드 처리 방식으로도 충분히 가능할 것 같습니다.
    "권한", "부여", "iam", "role", "역할"
]

slack_client = WebClient(token=SLACK_TOKEN)

def main(event, context):
    headers = event.get("headers", {})
    if "x-slack-retry-num" in headers: # 재시도 요청 무시하고 200 OK 응답
        retry_num = headers.get("x-slack-retry-num")
        logger.warning(f"Slack 재시도 요청 무시. {retry_num}번째")
        return {"statusCode": 200, "body": ""}

    body = json.loads(event.get("body", "{}"))
    event_type = body.get("type")

    if event_type == "url_verification":
        return body.get("challenge")

    if event_type == "event_callback":
        slack_event = body.get("event", {})
        handle_slack_event(slack_event)

    return {"statusCode": 200, "body": "OK"}

def handle_slack_event(event):
    event_type = event.get("type")

    if event_type == "message": 
        if event.get("bot_id") or event.get("thread_ts"):
            return
        
        if SLACK_CHANNEL_ID and event.get("channel") != SLACK_CHANNEL_ID: # 채널 필터링
            return
        
        user_question = event.get("text").lower()
        if any(keyword in user_question for keyword in IGNORE_KEYWORDS):
            logger.info("발견된 키워드: " + keyword)
            return
        process_message_event(event)

def process_message_event(event):
    channel_id = event.get("channel")
    user_question = event.get("text")
    user_id = event.get("user")
    thread_ts = event.get("ts")

    try:
        slack_client.reactions_add(
            channel=channel_id,
            name="bbengle",
            timestamp=thread_ts
        )
    except SlackApiError as e:
        logger.error(f"Slack 리액션 추가 실패: {e}")

    payload = {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "user_question": user_question,
        "user_id": user_id
    }

    try:
        lambda_client.invoke(
            FunctionName=RAG_CHAIN_LAMBDA_NAME,
            InvocationType="Event",
            Payload=json.dumps(payload)
        )
        logger.info(f"RAG 체인 람다 호출 성공: {RAG_CHAIN_LAMBDA_NAME}")
    except Exception as e:
        logger.error(f"RAG 체인 람다 호출 실패: {e}")
        try:
            slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"답변 생성에 실패했습니다: {e}"
            )
        except SlackApiError as slack_e:
            logger.error(f"Slack 메시지 전송 실패: {slack_e}")