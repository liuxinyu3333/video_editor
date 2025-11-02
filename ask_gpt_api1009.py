from calendar import c
from pathlib import Path
from typing import Tuple, List, Dict, Any
import csv
from use_gpt_api import *
from pathlib import Path
from typing import Iterator, Tuple, List, Dict, Any
from pathlib import Path
from typing import List, Dict, Any, Tuple



def iter_only_sub_txt_inputs(
    only_sub_dir: str | Path = "only_sub",
    *,
    max_chars: int = 120_000,
    assume_encoding: str = "utf-8",
) -> Iterator[Tuple[Path, List[Dict[str, Any]], str]]:
    """
    遍历 only_sub 目录下的所有 .txt 文件，并将每个文件转为可直接传给 Responses API 的 input。
    逐个 yield (txt_path, input_blocks, meta_note)

    - txt_path: 该文件的 Path
    - input_blocks: 传给 Responses API 的 input（list[{"role":"user","content":[{"type":"input_text","text": "..."}]}]）
    - meta_note: 可读说明，用于日志/打印

    注意：依赖同文件中的 txt_to_gpt_input()
    """
    base = Path(only_sub_dir)
    if not base.exists():
        raise FileNotFoundError(f"目录不存在：{base.resolve()}")
    if not base.is_dir():
        raise NotADirectoryError(f"不是目录：{base.resolve()}")

    # 递归遍历 only_sub 下的所有 .txt
    for p in sorted(base.rglob("*.txt")):
        # 跳过隐藏文件
        if any(part.startswith(".") for part in p.parts):
            continue
        input_blocks, note = txt_to_gpt_input(
            p,
            max_chars=max_chars,
            assume_encoding=assume_encoding,
        )
        yield p, input_blocks, note



def _read_text_with_fallback(p: Path, assume_encoding: str = "utf-8") -> tuple[str, str]:
    """优先用 assume_encoding 读取文本，失败则按常见编码回退；返回 (text, encoding_used)"""
    tried = [assume_encoding, "utf-8-sig", "gb18030", "latin-1"]
    for enc in tried:
        try:
            return p.read_text(encoding=enc), enc
        except Exception:
            continue
    # 兜底：以替换方式解码
    return p.read_bytes().decode("utf-8", errors="replace"), "utf-8~replace"



def txt_to_gpt_input(
    file_path: str | Path,
    *,
    max_chars: int = 1_200_000,
    assume_encoding: str = "utf-8",
) -> Tuple[List[Dict[str, Any]], str]:
    """
    将 TXT 文件转为可直接传给 Responses API 的 input。
    返回: (input_blocks, meta_note)
    """
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"文件不存在：{p}")

    text, enc = _read_text_with_fallback(p, assume_encoding=assume_encoding)

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    payload = (
        "【TXT文档开始】\n"
        + text
        + ("\n【...已截断，后续内容未包含...】" if truncated else "")
        + "\n【TXT文档结束】"
    )

    input_blocks = [
        {"role": "system", "content": [{"type": "input_text", "text": payload}]}
    ]
    meta_note = f"源文件: {p.name}\n类型: text/plain\n编码: {enc}\n长度: {len(text)}（截断: {truncated}）"
    return input_blocks, meta_note



def csv_to_gpt_input(
    file_path: str | Path,
    *,
    csv_max_rows: int = 80,           # 包含表头在内的最大输出行数
    max_chars: int = 120_000,         # 最终文本的最大字符数（再次保护）
    assume_encoding: str = "utf-8",
) -> Tuple[List[Dict[str, Any]], str]:
    """
    将 CSV 文件转为可直接传给 Responses API 的 input。
    - 自动识别分隔符（失败则默认逗号）
    - 输出为“管道分隔”的紧凑表格文本（含表头 + 前 N 行）
    返回: (input_blocks, meta_note)
    """
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"文件不存在：{p}")

    raw, enc = _read_text_with_fallback(p, assume_encoding=assume_encoding)

    # 猜分隔符
    try:
        sample = raw[:4096]
        dialect = csv.Sniffer().sniff(sample)
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ","

    # 读取 CSV
    rows: list[list[str]] = list(csv.reader(raw.splitlines(), delimiter=delimiter))
    row_count = len(rows)
    if row_count == 0:
        header, body = [], []
    else:
        header = rows[0]
        body = rows[1:] if row_count > 1 else []

    # 取前 csv_max_rows 行
    remain = max(csv_max_rows - 1, 0)
    body_view = body[:remain]
    truncated_rows = (1 + len(body_view)) < row_count  # 是否按行截断

    def row_to_line(r: list[Any]) -> str:
        return " | ".join("" if x is None else str(x) for x in r)

    lines: list[str] = []
    if header:
        lines.append(row_to_line(header))
    for r in body_view:
        lines.append(row_to_line(r))

    table_text = "\n".join(lines)

    payload = (
        "【CSV表开始】\n"
        f"列: {', '.join(header) if header else '(无表头)'}\n"
        "数据(管道分隔 | )：\n"
        + table_text
        + ("\n【...已按行截断，仅展示前若干行...】" if truncated_rows else "")
        + "\n【CSV表结束】"
    )

    # 再按字符长度保护一次
    truncated_chars = False
    if len(payload) > max_chars:
        payload = payload[:max_chars] + "\n【...已按字符数截断...】"
        truncated_chars = True

    input_blocks = [
        {"role": "user", "content": [{"type": "input_text", "text": payload}]}
    ]
    meta_note = (
        f"源文件: {p.name}\n"
        f"类型: text/csv\n"
        f"编码: {enc}\n"
        f"分隔符: '{delimiter}'\n"
        f"总行数: {row_count}\n"
        f"输出行数: {1 if header else 0} + {len(body_view)}（表头 + 数据）\n"
        f"行截断: {truncated_rows}；字符截断: {truncated_chars}"
    )
    return input_blocks, meta_note


def make_tag(filename: str, kind: str) -> str:
    """生成稳定可引用的来源标签，如 SRC:txt:junzhangbtc-zh.txt"""
    return f"SRC:{kind}:{Path(filename).name}"

def wrap_with_tag(blocks: List[Dict[str, Any]], tag: str) -> List[Dict[str, Any]]:
    # blocks 形如: [{"role":"user","content":[{"type":"input_text","text":"..."}]}]
    # 取出唯一那段文本，前后包上“来源标签”边界
    text0 = blocks[0]["content"][0]["text"]
    wrapped = (
        f"<<SOURCE {tag} BEGIN>>\n"
        f"{text0}\n"
        f"<<SOURCE {tag} END>>"
    )
    return [{"role":"user","content":[{"type":"input_text","text": wrapped}]}]


def main(csv_path :str = "BTCUSDT.csv"):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    csv_input, csv_note = csv_to_gpt_input(csv_path, csv_max_rows=500)
    csv_tag = make_tag(csv_path, "csv")
    csv_block = wrap_with_tag(csv_input, csv_tag)
    with open("gpt_replies.txt", "w", encoding="utf-8") as f:
        f.write("=== GPT批量回复结果 ===\n\n")
    user_prompt = ("你是一位加密货币短线交易博主，擅长用简洁但专业的口吻，在社交媒体上分析市场走势（txt文件中是你平常说话的模式）。 请根据我提供的csv文件中的每30分钟的比特币涨跌的数据（列名中是每一列数据的意义），生成一篇市场点评，要求： 1. **角色设定** - 你是经验丰富的交易员，熟悉 BTC/ETH 等主流币的技术面分析。 - 擅长用通俗的交易术语解释复杂走势，让读者快速理解市场逻辑。 2. **结构要求** - 开头打招呼，然后点出市场主线或主要操作思路（如“今天主力在进行双头清算”）。 - 按时间或逻辑顺序描述关键价格位置、突破/回落动作。 - 提及具体的关键点位（支撑位、阻力位）、K线周期（1小时、日K等）。 - 对未来可能的走势进行简短判断，并给出风险提示。 3. **语言风格** - 用交易圈常用词（如“清算”“支撑线”“阻力”“回踩”“突破”）。 - 口吻偏直接、判断明确，但不做绝对承诺。 - 句子多用短句，加入数字、价格位、时间点（突出数字点位）。 - 偶尔用括号补充说明。 4. **输出格式** - 不要分标题段落，保持社交媒体一段话的流畅阅读感。5. 使用txt文件中的说话风格，但不使用任何txt文件中的数据，然后要结合csv文件中的数据来生成文章。 - 文末可附一句简短总结或提醒。 一定要保证文章尽可能的符合真实人类的语言习惯，不要出现任何的表述使得文章像一个人工智能一样的表述，不要出现类似：基于你提供的30m数据，文章要以第一视角生成")    
    
    # user_prompt = ("你是一位在社交媒体上拥有十万粉丝的加密货币短线交易博主。你表达自然、接地气、有节奏感，习惯根据实时数据用人话分析市场。请根据我提供的CSV文件中的真实行情数据（列名已说明数据含义），生成一段市场点评文案，要求："
    #                 "1. **角色设定** - 你是一个实盘老手，说话像朋友聊天，不装专家。受众是“完全没接触过加密货币”的人。目标是让他们听得懂行情、感受到节奏、知道你现在的思路和操作倾向。"
    #                 "2. **结构要求** - 开头一句要吸引人（有节奏、有情绪）。说明当前行情状态（上涨 or 下跌、强 or 弱），引用CSV数据中的真实价格（如当前价、24小时高低点、支撑/阻力区间）。结合走势，给出开单建议，表述出自己前一天的收益。"
    #                 "3. **语言风格** - 句子短、有节奏感，像朋友圈发帖。多用顿号、感叹号。口语自然但不夸张。不要出现任何“AI”“模型”“CSV”“数据分析”等词。不要解释数据来源，只直接说出结论。"
    #                 "4. **输出格式** - 一段文字，不分段、不加标题。长度50～80字之间。所有价格、区间、涨跌幅必须真实取自CSV文件。用第一人称视角输出。"
    #                 "5. **禁止事项** - 不得出现“AI”“CSV”“根据文件”“计算结果”等字样；"

    #                 )    

    
    for txt_path, input_blocks, note in iter_only_sub_txt_inputs("only_sub"):
        txt_input, txt_note = txt_to_gpt_input(txt_path, max_chars=100_000)
        txt_tag = make_tag(txt_path, "txt")
        txt_block = wrap_with_tag(txt_input, txt_tag)

        prompt_block = [{
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": (
                    "下面是我的问题/任务，请仅使用我提供的资料作答。\n"
                    f"- 文本资料标签：{txt_tag}\n"
                    f"- 表格资料标签：{csv_tag}\n\n"
                    "请遵循：\n"
                    "1) 若两份资料相互矛盾，请优先以CSV中的时间序列数据为准。\n"
                    "2) 不要复述全部原文，只抽取与问题相关的要点。\n\n"
                    f"【我的问题 / 指令】\n{user_prompt}\n"
                )
            }]
        }]
        input_blocks = txt_block + csv_block + prompt_block
        answer = ask_model(client, input_blocks)
        print(answer.output_text)
        print("=========================================")
        with open("gpt_replies.txt", "a", encoding="utf-8") as f:
            f.write(f"=== 人物语气：{txt_path.name} ===\n")
            f.write(f"=== 币种：{csv_path} ===\n")
            f.write(answer.output_text)
            f.write("=========================================\n")
        

if __name__ == "__main__":
    main()
