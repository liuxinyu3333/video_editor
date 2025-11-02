# pip install openai==1.*
import os, time
from pathlib import Path
from openai import OpenAI
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
from typing import List
# 新增 imports
import re
import copy
import openai  # 捕获 openai.BadRequestError
import json



MODEL = "gpt-4o"
BATCH_SIZE = 6
SLEEP_BETWEEN_BATCH = 6
MAX_RETRIES = 3
PRICES = {
    # 按你实际价格改！这里只是示例
    "gpt-4o":      {"in": 4.25,  "out": 17.0, "cached_in": 2.125},
    "gpt-4o-mini": {"in": 0.15, "out": 0.6,  "cached_in": 0.075},
    "gpt-5":       {"in": 2.5, "out": 20.0,  "cached_in": 0.25},
}
CSV_PATH = "usage_log.csv"
TOTAL_COST_USD = 0.0  # 可选：累计
CONV_MAP_FILE = Path("conversation_map.json")#会话的id和对应的人物文案
# def _extract_usage(resp):
#     """
#     兼容新版/旧版 SDK：
#     - 新版: usage.prompt_tokens / usage.completion_tokens / usage.total_tokens
#     - 旧版或字典: usage['prompt_tokens'] 等
#     同时保留 prompt_cache_{hit,write}_tokens 字段（若存在）。
#     """
#     usage = getattr(resp, "usage", None)
#     if not usage:
#         return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_hit": 0, "cache_write": 0}

#     # 先尝试属性访问（新版 SDK 通常是对象）
#     try:
#         input_tokens  = int(getattr(usage, "prompt_tokens", 0) or 0)
#         output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
#         total_tokens  = int(getattr(usage, "total_tokens", 0) or 0)
#         cache_hit     = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
#         cache_write   = int(getattr(usage, "prompt_cache_write_tokens", 0) or 0)
#         return {
#             "input_tokens": input_tokens,
#             "output_tokens": output_tokens,
#             "total_tokens": total_tokens,
#             "cache_hit": cache_hit,
#             "cache_write": cache_write,
#         }
#     except Exception:
#         pass

#     # 若 usage 是 dict，则用键访问
#     if isinstance(usage, dict):
#         return {
#             "input_tokens":  int(usage.get("prompt_tokens", 0) or 0),
#             "output_tokens": int(usage.get("completion_tokens", 0) or 0),
#             "total_tokens":  int(usage.get("total_tokens", 0) or 0),
#             "cache_hit":     int(usage.get("prompt_cache_hit_tokens", 0) or 0),
#             "cache_write":   int(usage.get("prompt_cache_write_tokens", 0) or 0),
#         }

#     # 兜底
#     return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_hit": 0, "cache_write": 0}

def _load_conv_map() -> dict:
    try:
        if CONV_MAP_FILE.exists():
            return json.loads(CONV_MAP_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_conv_map(m: dict) -> None:
    CONV_MAP_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def ask_with_saved_conversation(client: OpenAI, input_blocks, txt_path):
    """
    给定 txt_path，自动读取/复用已保存的 conversation id；
    若本次产生了会话或会话 id 变化，则更新映射文件。
    返回 Responses 的 resp 对象（与 ask_model 一致）。
    """
    mp = _load_conv_map()
    key = str(Path(txt_path).resolve())
    conv_id = mp.get(key)
    resp = ask_model(client, input_blocks, conv_id=conv_id)
    new_conv = getattr(resp, "conversation", None)
    if new_conv:
        if mp.get(key) != new_conv:
            mp[key] = new_conv
            _save_conv_map(mp)
    return resp


# 新增：从打包后的 messages 里移除某个 image_url（返回移除的数量）
def _strip_bad_image_from_packed(msgs, bad_url: str) -> int:
    removed = 0
    for m in msgs:
        if m.get("role") != "user":
            continue
        new_content = []
        for part in m.get("content", []):
            if part.get("type") == "input_image" and str(part.get("image_url", "")).strip() == bad_url:
                removed += 1
                continue
            new_content.append(part)
        m["content"] = new_content
    return removed

# 可选：从错误消息里提取“下载失败的 URL”
def _extract_failed_url_from_err(err: Exception) -> str | None:
    text = getattr(err, "message", "") or str(err)
    m = re.search(r"Error while downloading\s+(https?://\S+?)\.", text)
    return m.group(1) if m else None




def _extract_usage(resp):
    """
    同时兼容：
    - Responses: usage.input_tokens / output_tokens / total_tokens
                 usage.input_tokens_details.cached_tokens
    - Chat:      usage.prompt_tokens / completion_tokens / total_tokens
                 usage.prompt_cache_hit_tokens / prompt_cache_write_tokens
    """
    usage = getattr(resp, "usage", None)
    if not usage:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_hit": 0, "cache_write": 0}

    # 优先按属性读取（SDK 常用对象形式）
    try:
        input_tokens  = int(getattr(usage, "input_tokens",  getattr(usage, "prompt_tokens", 0)) or 0)
        output_tokens = int(getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0)) or 0)
        total_tokens  = int(getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens))

        cache_hit = 0
        itd = getattr(usage, "input_tokens_details", None)
        if itd is not None:
            cache_hit = int(getattr(itd, "cached_tokens", 0) or 0)
        else:
            cache_hit = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)

        cache_write = int(getattr(usage, "prompt_cache_write_tokens", 0) or 0)

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cache_hit": cache_hit,
            "cache_write": cache_write,
        }
    except Exception:
        pass

    # 如果 usage 是 dict（某些环境会返回 dict）
    if isinstance(usage, dict):
        input_tokens  = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        total_tokens  = int(usage.get("total_tokens") or (input_tokens + output_tokens))
        itd = usage.get("input_tokens_details") or {}
        cache_hit = 0
        if isinstance(itd, dict):
            cache_hit = int(itd.get("cached_tokens") or 0)
        cache_hit = int(cache_hit or usage.get("prompt_cache_hit_tokens") or 0)
        cache_write = int(usage.get("prompt_cache_write_tokens") or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cache_hit": cache_hit,
            "cache_write": cache_write,
        }

    # 兜底
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_hit": 0, "cache_write": 0}


def _estimate_cost_usd(model: str, usage: dict) -> float:
    if model not in PRICES:
        raise KeyError(f"未配置 {model} 的价格，请在 PRICES 中添加。")
    p = PRICES[model]
    in_tok  = usage["input_tokens"]
    out_tok = usage["output_tokens"]
    cache_hit = min(usage.get("cache_hit", 0), in_tok)

    # 命中缓存部分按 cached_in 单价计；没配置就全按普通输入价
    if "cached_in" in p and cache_hit > 0:
        normal_in = max(in_tok - cache_hit, 0)
        cost_in = (normal_in / 1000000) * p["in"] + (cache_hit / 1000000) * p["cached_in"]
    else:
        cost_in = (in_tok / 1000000) * p["in"]
    cost_out = (out_tok / 1000000) * p["out"]
    return round(cost_in + cost_out, 6)

def _log_usage_csv(model: str, usage: dict, cost_usd: float, csv_path: str = CSV_PATH):
    # 时间使用欧洲/柏林时区
    ts = datetime.now(ZoneInfo("Europe/Berlin")).isoformat(timespec="seconds")
    header = ["time", "model", "input_tokens", "output_tokens", "cost_usd"]
    write_header = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(header)
        w.writerow([ts, model, usage.get("input_tokens",0), usage.get("output_tokens",0), f"{cost_usd:.6f}"])
# ==== end minimal cost & CSV logger ====


# 每批提炼要点（尽量短，降低成本与速率压力）
BATCH_PROMPT = (
    "请严格逐一从这些加密货币走势图（高清截图）中读取和提炼信息，避免使用常识或历史数据补全（使用中文）。要求如下："
    "1. 确认币种（如 BTC/USDT、ETH/USDT），直接从图表标题或界面文字读取。"
    "2. 仔细观察图表上的标注文字、红黄线、价格刻度，逐一识别3-5个关键拐点/结构。对每个点写明：- 大致日期/时间（按横轴读取，不要推测，写时间区间），- 对应价格（按纵轴或文字标注读取，不要编造）。"
    "3. 如果图上明确标有“支撑位”“阻力位”或画有横线，则记录下来，并写出对应价格（只按图上显示数值）。"
    "4. 输出时使用极短句的列表格式，保持中立，不做任何预测或建议。"
    "5. **禁止凭记忆或外部常识补数据**，只能写出图像中能清晰看到的数字和位置。"
)

def load_urls_from_txt(path: str):
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]



# 暂时弃用chat版本调用api的方法
"""
def build_image_messages_text_first(prompt_text: str, urls: list[str] = []):
    # 文本 + 多图（高清）
    content = [{"type": "text", "text": str(prompt_text)}]
    if urls:
        for u in urls:
            content.append({"type": "image_url", "image_url": {"url": str(u), "detail": "high"}})
    return [{"role": "user", "content": content}]

def ask_model(client: OpenAI, messages):
    for attempt in range(1, MAX_RETRIES+1):
        try:
            resp = client.chat.completions.create(model=MODEL, messages=messages)
            usage = _extract_usage(resp)
            cost  = _estimate_cost_usd(MODEL, usage)
            _log_usage_csv(MODEL, usage, cost)
            return resp.choices[0].message.content

        except Exception as e:
            print(f"[warn] 调用失败 {attempt}/{MAX_RETRIES}：{e}")
            time.sleep(2 * attempt)
    raise RuntimeError("连续重试失败")
"""

#使用responses调用api的方法
def build_image_messages_text_first(prompt_text: str, urls: list[str] = []):
    """
    Responses API 版：
    - 文本分片使用 {"type": "input_text", "text": ...}
    - 图像分片使用 {"type": "input_image", "image_url": ...}
    - 不再使用 Chat 的 "detail" 字段
    - 返回的是可直接放进 responses.create(input=...) 的消息数组
    """
    content = [{"type": "input_text", "text": str(prompt_text)}]
    if urls:
        for u in urls:
            content.append({"type": "input_image", "image_url": str(u)})
    return [{"role": "user", "content": content}]

# === 新增：把 N 组(6图+字幕)一次性打包进 Responses 的 input ===
def build_packed_groups_input(system_prompt: str, groups: list[tuple[list[str], str]], ack: str | None = None):
    """
    groups: [(urls6, subtitle_text_or_none), ...]
    生成可直接作为 responses.create(..., input=[]) 的消息数组。
    如果 ack 不为空，会在末尾追加一条“只回复 ack”的指令，用来“预热并建立会话”而不产生大量输出。
    """
    msgs = [
        {"role": "system", "content": [{"type": "input_text", "text": str(system_prompt)}]},
    ]
    content = [{"type": "input_text", "text": "以下内容包含多组(6图+字幕)。请完整读取并在下一次指令时统一作答。"}]
    for i, (urls, sub_text) in enumerate(groups, 1):
        content.append({"type": "input_text", "text": f"[GROUP {i}] 开始"})
        for u in urls:
            content.append({"type": "input_image", "image_url": str(u)})
        if sub_text:
            content.append({"type": "input_text", "text": "字幕：\n" + str(sub_text)})
        content.append({"type": "input_text", "text": f"[GROUP {i}] 结束"})
    msgs.append({"role": "user", "content": content})

    if ack:
        msgs.append({"role": "user", "content": [{"type": "input_text", "text": f"如果已读取全部 GROUP，仅回复：{ack}"}]})
    return msgs

# === 新增：发送一次“上下文预热请求”，持久化并取会话ID ===
def seed_context_and_get_conversation(client: OpenAI, packed_msgs):
    """
    用 build_packed_groups_input(...) 生成的 packed_msgs 发送一次最小回复(OK)的请求，
    开启 store(默认即为 True)，以便后续只发不同 prompt 复用同一上下文。
    返回 (conversation_id, ack_text)；若 SDK 不支持会话字段，则返回 (None, ack_text) 以便后续降级处理。
    """
    resp = client.responses.create(model=MODEL, input=packed_msgs, store=True)

    usage = _extract_usage(resp)
    cost  = _estimate_cost_usd(MODEL, usage)
    _log_usage_csv(MODEL, usage, cost)
    
    conv_id = getattr(resp, "conversation", None)  # 优先使用 SDK 提供的会话标识
    # 一些环境下可能没有 conversation 字段；此时我们做降级处理（见 main()）
    ack_text = getattr(resp, "output_text", "") or ""
    return conv_id, ack_text

# === 新增：在已建立的会话上继续对话，只发送新的 prompt ===
def ask_with_conversation(client: OpenAI, conversation_id: str, prompt_text: str) -> str:
    """
    基于既有会话对话：不再重发所有组，只发新的用户指令。
    """
    resp = client.responses.create(
        model=MODEL,
        conversation=conversation_id,
        input=[{"role": "user", "content": [{"type": "input_text", "text": str(prompt_text)}]}],
    )
    usage = _extract_usage(resp)
    cost  = _estimate_cost_usd(MODEL, usage)
    _log_usage_csv(MODEL, usage, cost)
    return resp.output_text



def ask_model(client: OpenAI, input_blocks, conv_id = None):
    for attempt in range(1, MAX_RETRIES+1):

        try:
            # Chat → Responses：改 messages=... 为 input=...
            resp = None
            if conv_id:
                resp = client.responses.create(model=MODEL,conversation=conv_id, input=input_blocks, store=True)
            else:
                resp = client.responses.create(model=MODEL, input=input_blocks, store=True)
            usage = _extract_usage(resp)
            cost  = _estimate_cost_usd(MODEL, usage)
            _log_usage_csv(MODEL, usage, cost)

            # Responses 提供便捷字段
            return resp

        except Exception as e:
            print(f"[warn] 调用失败 {attempt}/{MAX_RETRIES}：{e}")
            time.sleep(2 * attempt)
    raise RuntimeError("连续重试失败")



def main(subtitles: List[str] = [], urls : List[str] = []):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    urls = load_urls_from_txt("test_out.txt")
    print(f"共有 {len(urls)} 张图；分批提炼要点，然后合并生成一次性最终回答。")

    # === 阶段1：逐批提炼要点（只要短输出）===
    # === 阶段1：逐批提炼要点（每批 6 图 + 可选字幕片段）===
    batch_notes = []

    # 先按 6 张图切批；如果需要与 chunks 对齐，就只保留满 6 张的批次
    batches = list(chunk(urls, BATCH_SIZE))
    # full_batches = [b for b in batches if len(b) == BATCH_SIZE]

    if subtitles:
        # 有字幕片段时：一一配对（多余的批次或片段自动截断）
        pair_count = min(len(batches), len(subtitles))
        pairs = [(batches[i], subtitles[i]) for i in range(pair_count)]
    else:
        # 无字幕片段时：只传图片
        pairs = [(b, None) for b in batches]

        # === NEW: 一次把所有组载入 Responses 的会话上下文（只回“OK”以减少输出token）===
    # SYSTEM_PROMPT = "You are a diligent vision+text analyst. Read all groups and wait for the next instruction."
    # groups = pairs  # [(urls6, subtitle_or_None), ...] 直接用上面配好的 pairs
    # packed_msgs = build_packed_groups_input(SYSTEM_PROMPT, groups, ack="OK")
    # conv_id, ack = seed_context_and_get_conversation(client, packed_msgs)
    # print(f"[seed] 已加载全部组到上下文：{ack!r}; conversation={conv_id}")

    conv_id = ""
    for i, (batch, chunk_text) in enumerate(pairs, start=1):
        print(f"\n=== 批次 {i}（{len(batch)} 张）→ 提炼要点 ===")
        # 将对应的字幕片段拼进本批提示词
        if chunk_text:
            prompt_text = (
                BATCH_PROMPT
                + "\n\n对应字幕片段（恰好覆盖这 6 张图片时间段）：\n"
                + str(chunk_text)
            )
        else:
            prompt_text = BATCH_PROMPT

        messages = build_image_messages_text_first(prompt_text, batch)
        notes_rep = None
        if i == 1:
            notes_rep = ask_model(client, messages)
            conv_id = notes_rep.conversation
                      
        else:
            notes_rep = ask_model(client, messages, conv_id)
        notes = notes_rep.output_text  
        notes = notes.strip()
        print(notes)
        batch_notes.append(f"[批次 {i} 要点]\n{notes}")
        time.sleep(SLEEP_BETWEEN_BATCH)

    # === 阶段2：汇总所有批次要点 → 最终一次性输出 ===
    all_notes = "\n\n".join(batch_notes)

    # 如果你希望再给模型少量“关键图片”佐证（比如每10张挑1张），可以在这里选一小部分 URL
    # 以节省视觉 token；不需要的话就只给文本要点。
    key_urls = urls[::10]  # 每10张取1张，按需调整或置空 []
    prompt_text1 = (
        "你是一位加密货币短线交易博主，擅长用简洁但专业的口吻，在社交媒体上分析市场走势。 "
        "请根据我提供的压缩文件中的图片和字幕结合当前时间，生成一篇市场点评，要求： "
        "1. **角色设定** - 你是量化背景的交易员，熟悉 BTC/ETH 等主流币的指标联动（MA、RSI、VWAP、资金费率）。善于把复杂的指标和价格行为翻译成可执行的交易思路。"
        "2. **结构要求** - 开头直述市场主线或操作框架（如“资金在 1h VWAP 附近博弈”）。结合图片/字幕里的信息，加上“今天/此刻”市场的关键指标变化。描述关键支撑/阻力和对应的周期指标。给出两种可能路径和风险控制点。 "
        "3. **语言风格** - 直接，数字化表达（若/则/否则）。使用常见交易术语（清算、承压、突破、失效、风控）。少形容词，多点位数字。 "
        "4. **输出格式** - 不要分标题段落，保持社交媒体一段话的流畅阅读感。 - 文末可附一句简短总结或提醒。 "

    )
    prompt_text2 = (
        "你是一位加密货币短线交易博主，擅长用简洁但专业的口吻，在社交媒体上分析市场走势。 "
        "请根据我提供的压缩文件中的图片和字幕结合当前时间，生成一篇市场点评，要求： "
        "1. **角色设定** - 你是盘感派操盘手，专注 BTC/ETH 的价格行为与流动性区域。善于通过支撑阻力和假突破来提炼市场逻辑。"
        "2. **结构要求** - 开头点明当下的主要价格动作（如“市场刚扫过上沿流动性”）。按顺序描述扫单、回踩、承压或延续，配合具体价位。加入关键点位和时间周期。结尾给未来两种可能走势的简单判断。 "
        "3. **语言风格** - 短句快节奏，常用交易口语（扫单、卡位、拉回、回补）。口吻直接，有盘面感，但不绝对化。"
        "4. **输出格式** - 不要分标题段落，保持社交媒体一段话的流畅阅读感。 - 文末可附一句简短总结或提醒。 "

    )
    prompt_text3 = (
        "你是一位加密货币短线交易博主，擅长用简洁但专业的口吻，在社交媒体上分析市场走势。 "
        "请根据我提供的压缩文件中的图片和字幕结合当前时间，生成一篇市场点评，要求： "
        "1. **角色设定** - 你是风险经理型交易员，习惯结合 BTC/ETH 的波动特征做仓位管理。强调止损、仓位大小和分支场景应对。"
        "2. **结构要求** - 开头说明当前市场风险点或驱动因子（如资金杠杆过高）。给出关键点位和对应的仓位/止损方案。展示不同情境（基线、乐观、悲观）的触发条件与反应。最后强调纪律。 "
        "3. **语言风格** - 冷静克制，用数字和条件表达。常见词汇：仓位、止损、无效点、清算风险。 "
        "4. **输出格式** - 不要分标题段落，保持社交媒体一段话的流畅阅读感。 - 文末可附一句简短总结或提醒。 "

    )
    prompt_text4 = (
        "你是一位加密货币短线交易博主，擅长用简洁但专业的口吻，在社交媒体上分析市场走势。 "
        "请根据我提供的压缩文件中的图片和字幕结合当前时间，生成一篇市场点评，要求： "
        "1. **角色设定** - 你是教学型交易导师，善于把 BTC/ETH 的市场走势用通俗语言讲给新人听。习惯在点评中嵌入“方法论”和“操作流程”。"
        "2. **结构要求** - 开头指出市场结构（如箱体、三推、回踩）。按步骤描述：识别 → 关键位 → 入场/止损/目标 → 作废条件。结合图片/字幕信息，加上当前时间的走势变化。结尾提示复盘或学习点。 "
        "3. **语言风格** - 亲和简洁，复杂术语后加括号解释。多用“先…再…”、“如果…就…”的教学句式。 "
        "4. **输出格式** - 不要分标题段落，保持社交媒体一段话的流畅阅读感。 - 文末可附一句简短总结或提醒。 "

    )
    
    prompt_text5 = (
    "你是一位加密货币短线交易博主，擅长用简洁但专业的口吻，在社交媒体上分析市场走势。 "
    "请根据我提供的压缩文件中的图片和字幕结合当前时间，生成一篇市场点评，要求： "
    "1. **角色设定** - 你是经验丰富的交易员，熟悉 BTC/ETH 等主流币的技术面分析。 - 擅长用通俗的交易术语解释复杂走势，让读者快速理解市场逻辑。"
    "2. **结构要求** - 开头点出市场主线或主要操作思路（如“今天主力在进行双头清算”）。 - 按时间或逻辑顺序描述关键价格位置、突破/回落动作。 - 提及具体的关键点位（支撑位、阻力位）、K线周期（1小时、日K等）。 - 对未来可能的走势进行简短判断，并给出风险提示。 "
    "3. **语言风格** - 用交易圈常用词（如“清算”“支撑线”“阻力”“回踩”“突破”）。 - 口吻偏直接、判断明确，但不做绝对承诺。 - 句子多用短句，加入数字、价格位、时间点（突出数字点位）。 - 偶尔用括号补充说明。 "
    "4. **输出格式** - 不要分标题段落，保持社交媒体一段话的流畅阅读感。 - 文末可附一句简短总结或提醒。 "

    )
    #prompt_text1, prompt_text2, prompt_text3, prompt_text4,
    prompts = [ prompt_text5]
    #构造最终请求：文本（最终PROMPT + 所有要点） + 少量关键图（可选）
    Path("middle_points_output.txt").write_text(all_notes , encoding="utf-8")

    for idx, p in enumerate(prompts, start=1):
        final_text_block = p + "\n\n对应字幕片段（恰好覆盖这 6 张图片时间段）：\n" + all_notes

        final_answer = []
        final_messages = build_image_messages_text_first(final_text_block, key_urls)

        print("\n=== 生成最终回答 ===")
        final_answer.append( ask_model(client, final_messages, conv_id))
        final_answer.append( ask_model(client, final_messages, conv_id))
        print("\n" + final_answer[0].output_text +"\n"+final_answer[1].output_text)

        if idx == 1:
            Path("final_output.txt").write_text(final_answer[0].output_text, encoding="utf-8")
            with Path("final_output.txt").open("a", encoding="utf-8") as f:
                f.write("\n" + final_answer[1].output_text)

        else:
            with Path("final_output.txt").open("a", encoding="utf-8") as f:
                f.write("======回答1======\n" + final_answer[0].output_text +"\n =====回答2======\n"+ final_answer[1].output_text )

        print("\n已写入 final_output.txt")

    
    # for p in prompts:
    #     if conv_id:
    #         print("\n=== 基于共享上下文生成 ===")
    #         final_answer = ask_with_conversation(client, conv_id, p)
    #     else:
    #         # 降级：若 SDK 未返回会话ID，则沿用旧逻辑（携带要点与少量图片）
    #         final_text_block = p + "\n\n下面是按批次整理的要点，请综合这些要点写一段最终点评：\n" + all_notes
    #         final_messages = build_image_messages_text_first(final_text_block, key_urls)
    #         print("\n=== 生成最终回答（降级：无会话） ===")
    #         final_answer = ask_model(client, final_messages)

    #     print("\n" + final_answer)
    #     Path("final_output.txt").write_text(final_answer, encoding="utf-8")
    #     print("\n已写入 final_output.txt")

if __name__ == "__main__":
    main()
