from openai import OpenAI
import os, sys

# 1) 检查是否有 Key
if not os.environ.get("OPENAI_API_KEY"):
    print("未检测到环境变量 OPENAI_API_KEY，请先设置。", file=sys.stderr)
    sys.exit(1)


#import os; k=os.environ.get("OPENAI_API_KEY",""); print((k[:6]+"..."+k[-4:]) if k else "NO_KEY")


# 2) 发一个最小请求
client = OpenAI()
try:
    resp = client.responses.create(
        model="gpt-4o",
        input="连通性测试：请只回复 pong"
    )
    # 3) 打印答案（应为：pong）
    print(resp.output_text.strip())
except Exception as e:
    # 出错时把错误类别+信息打印出来，便于排查
    print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
    raise
