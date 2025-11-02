import ask_gpt_api1009
import get_binance
import Email_sender
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+
import time
import argparse

coins = ["BTCUSDT", "ETHUSDT"]
#, "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "LUNAUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT"

def us_time_mdH(tz: str = "America/New_York") -> str:
    """返回形如 '10月11日14时' 的当前美国时间（默认东部时间）。"""
    now = datetime.now(ZoneInfo(tz))
    return f"{now.month}月{now.day}日{now.hour}时"

def pipline (typ : str = "BTCUSDT", email: str = "xinyu.liu1@rwth-aachen.de"):
    csv_path = get_binance.main(typ)
    ask_gpt_api1009.main(csv_path)
    files_to_send = ["gpt_replies.txt"]
    #Email_sender.main()
    Email_sender.main(
        body_text= f"（美国东部时间：{us_time_mdH()}）",
        target_email=email,
        filepaths= files_to_send
    )
def main(email: str = "Jingze.Gao@qq.com"):
    for ele in coins:
        pipline(ele, email)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行工作流")
    parser.add_argument("--run-once", type=bool, default=False, help="仅运行一次")
    parser.add_argument("--sleep-time", type=int, default=6, help="睡眠时间")
    parser.add_argument(
        "--coins",
        nargs="+",                     # 接收一个或多个值
        default=["BTCUSDT", "ETHUSDT"],# 默认值
        help="运行哪些币种: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, ADAUSDT, XRPUSDT, LUNAUSDT, DOTUSDT, DOGEUSDT, AVAXUSDT"
    )
    parser.add_argument("--email", type=str, default="Jingze.Gao@qq.com", help="发送邮件的邮箱")
    args = parser.parse_args()
    coins = args.coins
    if args.run_once:
        main()
    else:
        while True :
            main()
            time.sleep(args.sleep_time * 3600)

    