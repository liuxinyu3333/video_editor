import json, time, shutil
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import video_loader
import video_cut
import upload_to_gpt


def _read_new_records(manifest_path: Path, since_ts: int) -> List[Dict[str, Any]]:
    if not manifest_path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with manifest_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if int(rec.get("created_at", 0)) >= since_ts:
                records.append(rec)
    return records


def _zip_frames_dir(frames_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    # shutil.make_archive expects base_name without extension
    base = zip_path.with_suffix("")
    # Remove previous archive if exists
    for ext in (".zip",):
        p = base.with_suffix(ext)
        if p.exists():
            p.unlink()
    shutil.make_archive(str(base), "zip", root_dir=str(frames_dir))


def _prepare_video_folder_and_move_txt(video_path: Path) -> Path:
    """Create a per-video folder under the uploader directory and move the subtitle txt into it.
    Returns the created folder path.
    """
    video_dir = video_path.parent
    video_base = video_path.stem
    target_dir = video_dir / video_base
    target_dir.mkdir(parents=True, exist_ok=True)

    txt_path = video_path.with_suffix(".txt")
    if txt_path.exists():
        target_txt = target_dir / txt_path.name
        if target_txt.exists():
            target_txt.unlink()
        shutil.move(str(txt_path), str(target_txt))
    return target_dir

def _record_result(result_log: Path, video_folder: Path, files: List[Path]) -> None:
    result_log.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "video_folder": str(video_folder.resolve()),
        "files": [str(f.resolve()) for f in files if f.exists()]
    }
    with result_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    start_ts = int(time.time())
    video_loader.main()
    manifest_path = Path(video_loader.MANIFEST_PATH)

    new_records = _read_new_records(manifest_path, since_ts=start_ts)
    if not new_records:
        print("[pipeline] 本次无新增下载记录，结束。")
        return

    out_root = Path(video_cut.DEFAULT_OUTPUT_DIR)
    out_root.mkdir(parents=True, exist_ok=True)

    result_log = Path(video_loader.SAVE_DIR) / "results.jsonl"
   # 在项目根目录记录结果

    for rec in new_records:
        v = rec.get("video_path")
        s = rec.get("subtitle_path")
        if not v or not s:
            continue
        vpath, spath = Path(v), Path(s)
        if not vpath.exists() or not spath.exists():
            continue

        # 抽帧
        video_cut.process_one_video(vpath, spath, out_root, max_subs=0, similarity_threshold=5)

        frames_dir = video_cut._choose_out_dir(out_root, uploader=vpath.parent.name, base=vpath.stem)
        if not frames_dir.exists():
            print(f"[pipeline] 未找到帧目录：{frames_dir}")
            continue

        video_folder = _prepare_video_folder_and_move_txt(vpath)
        zip_path = video_folder / "frames.zip"
        _zip_frames_dir(frames_dir, zip_path)

        # 清理只保留 zip 与 txt
        for child in video_folder.iterdir():
            if child.name.lower().endswith(".zip"):
                continue
            if child.name.lower().endswith(".txt"):
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except Exception:
                    pass

        # === 新增：记录结果 ===
        files = [zip_path, video_folder / (vpath.stem + ".txt")]
        _record_result(result_log, video_folder, files)

        print(f"[pipeline] 完成：{vpath.stem} -> {zip_path}")


def run_one_creator(channel_url: str, pick_n: int = 1) -> None:
    """
    用现有函数跑通：指定单个博主，下载最新N个视频（默认1个）→ 抽帧 → 打包到视频同名文件夹，只保留 frames.zip 与 .txt
    """
    # 1) 解析频道，拿到最新视频URL
    print(f"\n== 单博主模式：{channel_url}")
    entries = video_loader.fetch_channel_videos(channel_url)                # 扁平元数据（快） 
    urls = video_loader.pick_latest_urls_from_entries(entries, pick_n)      # 过滤直播/短视频/正则关键词等
    if not urls:
        print("（筛选后无匹配的视频）")
        return

    # 如需先按“是否有字幕”筛一次（取决于你的 REQUIRE_SUBTITLES 等设置）
    targets: List[Tuple[str, Optional[List[str]]]]
    if (video_loader.REQUIRE_SUBTITLES or 
        video_loader.REQUIRE_MANUAL_SUBS or 
        (video_loader.ALLOWED_SUB_LANGS and len(video_loader.ALLOWED_SUB_LANGS) > 0)):
        targets = video_loader.filter_channel_targets_by_subtitles(urls)
        if not targets:
            print("（频道模式：无满足字幕条件的视频）")
            return
    else:
        targets = [(u, None) for u in urls]

    # 2) 逐条下载（内部会：挑字幕语言 → yt-dlp → 重命名为 YYYY-MM-DD-作者-编号.ext → 生成同名 .txt → 追加 manifest）
    start_ts = int(time.time())
    for u, langs in targets:
        video_loader.download_one(u, preferred_langs_from_search=langs)

    # 3) 读取本次新增记录（manifest里 created_at >= start_ts 的）
    manifest_path = Path(video_loader.MANIFEST_PATH)
    new_records = []
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line: 
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if int(rec.get("created_at", 0)) >= start_ts:
                new_records.append(rec)

    if not new_records:
        print("[single] 本次无新增下载记录。")
        return

    # 4) 抽帧 → 打包zip → 移入视频同名文件夹（只保留 zip 与 txt）
    out_root = Path(video_cut.DEFAULT_OUTPUT_DIR)
    out_root.mkdir(parents=True, exist_ok=True)

    for rec in new_records:
        v = rec.get("video_path")
        s = rec.get("subtitle_path")
        if not v or not s:
            continue
        vpath, spath = Path(v), Path(s)
        if not vpath.exists() or not spath.exists():
            continue

        # 4.1 抽帧（按字幕条目的起点/中点/终点各取一帧，自动去重）
        video_cut.process_one_video(
            vpath, spath, out_root,
            max_subs=0,               # 0=不限制；可改小加速
            similarity_threshold=5     # 感知哈希相似阈值
        )

        # 4.2 找到该视频对应的帧目录（video_cut 的内部路径规则）
        frames_dir = video_cut._choose_out_dir(out_root, uploader=vpath.parent.name, base=vpath.stem)
        if not frames_dir.exists():
            print(f"[single] 未找到帧目录：{frames_dir}")
            continue

        # 4.3 在上传者目录下创建“同名文件夹”，并把 .txt 移进去
        video_folder = _prepare_video_folder_and_move_txt(vpath)
        files_to_send = []
        # 4.4 打包 frames.zip
        zip_path = video_folder / "frames.zip"
        new_txt_path = video_folder / f"{vpath.stem}.txt"

        _zip_frames_dir(frames_dir, zip_path)

        # 4.5 清理，只保留 frames.zip 和 .txt（与 pipeline 一致）
        for child in video_folder.iterdir():
            name = child.name.lower()
            if name.endswith(".zip") or name.endswith(".txt"):
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except Exception:
                    pass
        files_to_send = [zip_path, new_txt_path]
        """
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
        """
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
        for p in prompts:
            upload_to_gpt.run(p, files_to_send)
        print(f"[single] 完成：{vpath.stem} -> {zip_path}")
        # video_loader._clean_storage()



if __name__ == "__main__":
    
   # run_one_creator("https://www.youtube.com/@KoluniteVIP")
    # main()
    sources = video_loader.SOURCES
    try:
        TZ = ZoneInfo("America/New_York")
    except Exception:
        TZ = None  # 没有 zoneinfo 就用本地时区

    while True :
        now = datetime.now()
        for ele in sources:
            run_one_creator(ele)
        if now.hour >= 7 and now.hour <= 12:
            time.sleep(1800)
        if now.hour > 12 and now.hour <= 24:
            time.sleep(3600)
        if now.hour >= 0 and now.hour < 7 :
            time.sleep(7200)


    

    # # files_to_send = [
    # #     r"E:\coin_works\project\video_storage\DA 交易者聯盟\2025-08-22-DA交易者聯盟-1\2025-08-22-DA交易者聯盟-1.txt",    # 改成你的绝对路径
    # #     r"E:\coin_works\project\video_storage\DA 交易者聯盟\2025-08-22-DA交易者聯盟-1\frames.zip",  # 改成你的绝对路径
    # # ]
    
    # while True:
    #     now = datetime.now(TZ) if TZ else datetime.now()
    #     nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    #     time.sleep((nxt - now).total_seconds())
    #     try:
    #         main()  # 每天 00:00 执行一次
    #         upload_to_gpt.batch_process_to_gpt(prompt_text)
    #         Email_sender.main()
    #     except Exception:
    #         import traceback;
    
    #         traceback.print_exc()
    #     time.sleep(5)  # 防抖，避免误触发


