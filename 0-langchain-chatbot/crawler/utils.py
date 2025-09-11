from datetime import datetime, timedelta, timezone
from typing import Optional, Iterable, Dict, List
import os, re, json

import boto3
from slack_sdk import WebClient
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2")
S3_BUCKET = os.environ["S3_BUCKET"]
S3_PREFIX = os.getenv("S3_PREFIX", "/")

slack = WebClient(token=SLACK_BOT_TOKEN)
s3 = boto3.client("s3", region_name=AWS_REGION)
KST = timezone(timedelta(hours=9))

# 메시지 파싱 정규식
MENTION_RE = re.compile(r"<@([A-Z0-9]+)>") # <@U13314324521> 형태
CHANNEL_RE = re.compile(r"<#([A-Z0-9]+)\|([^>]+)>") # <#C424124244|999-general-tech-qna> 형태
URL_RE = re.compile(r"<(https?://[^|>]+)(?:\|([^>]+))?>") # <https://slackslacksalcks.com|예시> 형태

# Slack 관련
def get_channel_messages(start_time: Optional[float], end_time: Optional[float]) -> Iterable[Dict]:
    cursor = None

    while True:
        params = {
            "channel": SLACK_CHANNEL_ID,
            "limit": 200,
            "cursor": cursor
        }

        if start_time:
            params["oldest"] = str(start_time)
        if end_time:
            params["latest"] = str(end_time)

        resp = slack.conversations_history(**params)
        messages = resp.get("messages", [])

        for msg in messages:
            yield msg # 계속 리턴

        next_cursor = resp.get("response_metadata", {}).get("next_cursor")

        if not next_cursor:
            break # 끝
        cursor = next_cursor
        
def get_thread_messages(thread_ts: str) -> Iterable[Dict]:
    messages = []

    try:
        resp = slack.conversations_replies(channel=SLACK_CHANNEL_ID, ts=thread_ts)
        messages.extend(resp.get("messages", []))
        
        cursor = resp.get("response_metadata", {}).get("next_cursor") # 더 있나?
        while cursor:
            resp = slack.conversations_replies(channel=SLACK_CHANNEL_ID, ts=thread_ts, limit=200, cursor=cursor)
            messages.extend(resp.get("messages", []))
            cursor = resp.get("response_metadata", {}).get("next_cursor")
    except Exception as e:
        print(f"스레드 메시지 다녀오다가 에러 발생: {e}")

    return messages

def get_permalink(ts: str) -> Optional[str]:
    try:
        resp = slack.chat_getPermalink(channel=SLACK_CHANNEL_ID, message_ts=ts)
        return resp.get("permalink")
    except Exception as e:
        print(f"스레드 링크 가져오다가 에러 발생: {e}")
        return None

def get_user_names(user_ids: List[str]) -> Dict[str, str]:
    user_names = {}

    for user_id in user_ids:
        try:
            info = slack.users_info(user=user_id)
            profile = info["user"]["profile"]
            
            name = profile.get("display_name")
            user_names[user_id] = name
        except Exception as e:
            user_names[user_id] = user_id # 그냥 ID로 
    return user_names

# Markdown 관련

def kst_str(ts: str) -> str:
    sec = int(ts.split(".")[0])
    dt = datetime.fromtimestamp(sec, tz=timezone.utc).astimezone(KST)
    return dt.strftime("%Y-%m-%d %H:%M")

def normalize_text(t: str, user_map: Dict[str, str]) -> str:
    t = URL_RE.sub(lambda m: f"[{m.group(1)}]({m.group(1)})", t)
    t = MENTION_RE.sub(lambda m: f"@{user_map.get(m.group(1), m.group(1))}", t) # 유저 못 찾는 에러 발생 -> 그냥 ID로 대체
    t = CHANNEL_RE.sub(lambda m: f"#{m.group(1)}", t)

    return t

def yaml_frontmatter(data: Dict[str, object]) -> str:
    lines = ["---"]
    for k, v in data.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v}")
    lines.append("---\n")
    return "\n".join(lines)

def render_markdown(messages: List[Dict]) -> str:
    assert messages, "messages empty"
    root = messages[0]
    user_ids = [m.get("user") for m in messages if m.get("user")]
    user_map = get_user_names(user_ids)

    fm = {
        "doc_type": "slack_thread",
        "thread_ts": root.get("thread_ts", root["ts"]),
        "root_permalink": get_permalink(root["ts"]) or "",
    }

    md = [yaml_frontmatter(fm)]
    md.append("# 질문")
    md.append(normalize_text(root.get("text", ""), user_map))
    
    if len(messages) > 1:
        md.append("\n# 답변")
        for m in messages[1:]:
            answer_text = normalize_text(m.get("text", ""), user_map)
            if answer_text.strip():
                md.append(f"\n{answer_text}")

    return "\n".join(md).strip() + "\n"


# S3 관련

def get_s3_key(thread_ts: str) -> str:
    sec = int(thread_ts.split(".")[0])
    kst_dt = datetime.fromtimestamp(sec, timezone.utc).astimezone(KST)
    year = kst_dt.strftime("%Y")
    month = kst_dt.strftime("%m")
    day = kst_dt.strftime("%d")

    return f"{S3_PREFIX}/threads/{year}/{month}/{day}/{thread_ts}.md"

def s3_upload(key: str, body: str) -> None:
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body.encode("utf-8"), ContentType="text/markdown; charset=utf-8")
    except Exception as e:
        print(f"{key}가 이미 존재하거나 or 다른 이유로 실패: {e}")

# Parser
def parse_date_range(start: Optional[str], end: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    oldest = None
    latest = None

    if start:
        # 기간의 시작이 주어졌을 때
        ds = datetime.fromisoformat(start).replace(tzinfo=KST)
        oldest = ds.timestamp()
    if end:
        # 기간의 끝이 주어졌을 떄
        de = datetime.fromisoformat(end).replace(tzinfo=KST) + timedelta(days=1) - timedelta(milliseconds=1) # 23시 59분 59.99초까지 포함되도록
        latest = de.timestamp()
    return oldest, latest