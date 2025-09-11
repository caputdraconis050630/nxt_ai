import argparse
from typing import Set
from utils import get_channel_messages, get_thread_messages, render_markdown, parse_date_range, get_s3_key, s3_upload


def main():
    # 옵션 파싱
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    oldest, latest = parse_date_range(args.start, args.end)

    seen: Set[str] = set()
    saved = 0

    for message in get_channel_messages(start_time=oldest, end_time=latest): # 채널 메시지(yield 사용!)
        thread_ts = message.get("thread_ts", message["ts"])
        if thread_ts in seen:
            continue
        seen.add(thread_ts)
        
         # 기간 필터링
        root_ts = float(thread_ts.split(".")[0])
        if oldest and root_ts < oldest:
            continue
        if latest and root_ts > latest:
            continue

        msgs = get_thread_messages(thread_ts) # 스레드 메시지
        if not msgs:
            continue
        md = render_markdown(msgs)
        key = get_s3_key(thread_ts)
        s3_upload(key, md)
        saved += 1
        if saved % 50 == 0:
            print(f"saved {saved} threads… last={thread_ts}")

    print("끝!")

if __name__ == "__main__":
    main()
