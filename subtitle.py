import subprocess
import locale
import re
from typing import List

def list_sub_langs(url: str) -> List[str]:
    url = url.strip()  # 去掉首尾空白，防止意外空格
    enc = locale.getpreferredencoding(False) or "utf-8"
    try:
        proc = subprocess.run(
            ["yt-dlp", "--list-subs", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError("未找到 yt-dlp，请确认已安装并加入 PATH。")

    out = proc.stdout.decode(enc, errors="replace")

    langs = set()
    section = None  # None / "subs" / "auto"
    row_re = re.compile(r"^\s*([a-zA-Z0-9._-]+)\s+.+$")

    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue

        low = s.lower()
        # 关键修正：用“包含”而不是 startswith，兼容 "[info] Available ..."
        if "available subtitles for" in low:
            section = "subs"
            continue
        if "available automatic captions" in low:
            section = "auto"
            continue
        # 跳过表头
        if "language" in low and "format" in low:
            continue

        if section in ("subs", "auto"):
            m = row_re.match(line)
            if m:
                langs.add(m.group(1))

    return sorted(langs)

# ---- 示例 ----
if __name__ == "__main__":
    test_url = "https://www.youtube.com/watch?v=lq-eygisE68 "
    print(list_sub_langs(test_url))
