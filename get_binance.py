import pandas as pd
import requests

BTC = "BNBUSDT"
INTERVAL = "30m"
LIMIT = 100

def main(coin: str = BTC) -> str:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": coin, "interval": INTERVAL, "limit": LIMIT}
    data = requests.get(url, params=params, timeout=15).json()

    cols = [
        "open_time","open","high","low","close","volume","close_time",
        "quote_asset_volume","number_of_trades",
        "taker_buy_base_asset_volume","taker_buy_quote_asset_volume","ignore"
    ]
    df = pd.DataFrame(data, columns=cols)

    # 转成数值类型
    num_cols = ["open","high","low","close","volume"]
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")

    # 增加易读时间（美东）
    df["open_time_us"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)\
                            .dt.tz_convert("America/New_York")

    # 只保留最关键列（最小集）
    keep_cols = ["open_time_us","open","high","low","close","volume","number_of_trades"]
    df = df[keep_cols]
    targ = coin+".csv"
    df.to_csv(targ, index=False, encoding="utf-8")
    print("已写入"+targ)
    return targ
    

if __name__ == "__main__":
    main()
