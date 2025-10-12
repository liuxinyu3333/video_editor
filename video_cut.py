import argparse, json, os, re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Set
import ffmpeg
from PIL import Image
import imagehash
from subtitle_enhance import Enhancer  # 新增



PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_STORAGE_DIR = PROJECT_ROOT / "video_storage"
DEFAULT_MANIFEST = DEFAULT_STORAGE_DIR / "manifest.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "frames_output"

# 线程安全打印，避免多线程输出打架

def tprint(*args, **kwargs):
    print(*args, **kwargs)

@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str

def _find_font_for_cjk() -> Optional[str]:
    candidates = [
        r"C:\\Windows\\Fonts\\msyh.ttc", r"C:\\Windows\\Fonts\\msyhbd.ttc",
        r"C:\\Windows\\Fonts\\simhei.ttf", r"C:\\Windows\\Fonts\\simfang.ttf",
        r"C:\\Windows\\Fonts\\simsun.ttc", r"C:\\Windows\\Fonts\\arialuni.ttf",
    ]
    for p in candidates:
        if Path(p).exists(): return p
    return None

def _parse_time_to_seconds(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        else:
            return float(ts)
    except Exception:
        return 0.0

def _parse_vtt(path: Path) -> List[SubtitleEntry]:
    entries = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.rstrip("\n") for ln in f]
    i = 0
    if lines and lines[0].strip().upper().startswith("WEBVTT"): i = 1
    time_re = re.compile(r"^(\d{1,2}:)?\d{2}:\d{2}[\.,]\d{1,3} \-\-\> (\d{1,2}:)?\d{2}:\d{2}[\.,]\d{1,3}")
    while i < len(lines):
        if lines[i].strip() and not time_re.match(lines[i]):
            i += 1
            continue
        if i >= len(lines): break
        if not time_re.match(lines[i]):
            i += 1
            continue
        time_line = lines[i]
        i += 1
        try:
            left, right = time_line.split("-->")
            start_s = _parse_time_to_seconds(left.strip())
            end_s = _parse_time_to_seconds(right.strip().split(" ")[0])
        except Exception:
            continue
        text_lines = []
        while i < len(lines) and lines[i].strip() != "":
            text_lines.append(lines[i])
            i += 1
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        text = "\n".join(text_lines).strip()
        if end_s <= start_s: end_s = start_s + 0.5
        entries.append(SubtitleEntry(start=start_s, end=end_s, text=text))
    return entries

def _parse_srt(path: Path) -> List[SubtitleEntry]:
    entries = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    blocks = re.split(r"\r?\n\r?\n+", content)
    for block in blocks:
        lines = [ln.strip("\ufeff") for ln in block.splitlines() if ln.strip() != ""]
        if not lines: continue
        time_idx = 0
        if re.match(r"^\d+$", lines[0]): time_idx = 1
        if time_idx >= len(lines): continue
        time_line = lines[time_idx]
        if "-->" not in time_line: continue
        left, right = time_line.split("-->")
        start_s = _parse_time_to_seconds(left.strip())
        end_s = _parse_time_to_seconds(right.strip())
        text = "\n".join(lines[time_idx + 1 :]).strip()
        if end_s <= start_s: end_s = start_s + 0.5
        entries.append(SubtitleEntry(start=start_s, end=end_s, text=text))
    return entries

def parse_subtitles(path: Path) -> List[SubtitleEntry]:
    suffix = path.suffix.lower()
    if suffix == ".vtt": return _parse_vtt(path)
    if suffix == ".srt": return _parse_srt(path)
    raise ValueError(f"Unsupported subtitle format: {suffix}")

def get_video_duration(video_path: Path) -> float:
    try:
        probe = ffmpeg.probe(str(video_path))
        fmt = probe.get("format", {})
        dur = fmt.get("duration")
        if dur: return float(dur)
        for st in probe.get("streams", []):
            if st.get("codec_type") == "video" and st.get("duration"):
                return float(st["duration"])
    except Exception:
        pass
    return 0.0

def _ensure_parent_dir(p: Path): p.parent.mkdir(parents=True, exist_ok=True)

def extract_frame(video_path: Path, t_seconds: float, out_image: Path) -> bool:
    _ensure_parent_dir(out_image)
    try:
        t = max(t_seconds, 0.0)
        try:
            (ffmpeg.input(str(video_path), ss=t)
                   .output(str(out_image), vframes=1, q=2, loglevel="error")
                   .overwrite_output().run())
        except Exception:
            (ffmpeg.input(str(video_path))
                   .filter('fps', fps=30)
                   .trim(start=t, end=t+0.1)
                   .setpts('PTS-STARTPTS')
                   .output(str(out_image), vframes=1, q=2, loglevel="error")
                   .overwrite_output().run())
        return out_image.exists() and out_image.stat().st_size > 0
    except Exception as e:
        tprint(f"[ffmpeg] 抽帧失败 @{t_seconds:.3f}s: {e}")
        return False

def calculate_image_hash(image_path: Path) -> Optional[str]:
    try:
        with Image.open(image_path) as img:
            if img.mode != 'RGB': img = img.convert('RGB')
            hash_value = imagehash.phash(img)
            return str(hash_value)
    except Exception as e:
        tprint(f"[warn] 计算图像哈希失败：{image_path} | {e}")
        return None

def is_similar_to_previous(image_path: Path, previous_hashes: Set[str], similarity_threshold: int = 5) -> bool:
    if not previous_hashes: return False
    current_hash = calculate_image_hash(image_path)
    if not current_hash: return False
    for prev_hash in previous_hashes:
        hamming_distance = sum(c1 != c2 for c1, c2 in zip(current_hash, prev_hash))
        if hamming_distance <= similarity_threshold: return True
    return False

def add_watermark(image_path: Path, subtitle_text: str, start_s: float, end_s: float): return

def _sec_to_hhmmssms(t: float) -> str:
    ms = int(round((t - int(t)) * 1000))
    s = int(t) % 60
    m = (int(t) // 60) % 60
    h = int(t) // 3600
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def _sec_to_fname_ts(t: float) -> str:
    ms = int(round((t - int(t)) * 1000))
    s = int(t) % 60
    m = (int(t) // 60) % 60
    h = int(t) // 3600
    return f"{h:02d}-{m:02d}-{s:02d}-{ms:03d}"

_ILLEGAL_WIN_CHARS = re.compile(r'[<>:"/\\|?*]')

def _safe_for_filename(name: str, max_len: int = 120) -> str:
    cleaned = _ILLEGAL_WIN_CHARS.sub('_', name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(' .')
    return cleaned[:max_len]

def _hash8(s: str) -> str:
    import hashlib
    return hashlib.md5(s.encode('utf-8', errors='ignore')).hexdigest()[:8]

def _choose_out_dir(out_root: Path, uploader: str, base: str) -> Path:
    uploader_s = _safe_for_filename(uploader, max_len=40)
    base_s = _safe_for_filename(base, max_len=80)
    d = out_root / uploader_s / base_s
    if len(str(d)) > 230:
        h = _hash8(str(out_root) + uploader + base)
        d = out_root / uploader_s / f"vid_{h}"
    return d


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """返回区间重叠时长（秒），无重叠为 0"""
    left = max(a_start, b_start)
    right = min(a_end, b_end)
    return max(0.0, right - left)

def collect_subtitles_text(entries: List[SubtitleEntry], win_start: float, win_end: float) -> str:
    """
    收集 [win_start, win_end] 区间内与字幕有重叠的条目文本，按时间顺序拼接。
    多行字幕保持原样；不同条目之间用换行分隔，必要时可改为空格。
    """
    picked = []
    for e in entries:
        if _overlap(e.start, e.end, win_start, win_end) > 0.0:
            picked.append((e.start, e.end, e.text))
    picked.sort(key=lambda x: x[0])
    texts = []
    for (s, e, t) in picked:
        if t.strip():
            texts.append(t.strip())
    return "\n".join(texts).strip()




def process_one_video(video_path: Path, subtitle_path: Path, out_root: Path, max_subs: int = 0, similarity_threshold: int = 5, subs_per_chunk: int = 0, write_chunks: bool = True) -> List[str]:
    entries = parse_subtitles(subtitle_path)
    enhancer = Enhancer()


    if not entries:
        tprint(f"[skip] 无字幕条目：{subtitle_path}")
        return

    duration = get_video_duration(video_path)
    if duration <= 0: tprint(f"[warn] 视频时长探测失败，仍尝试抽帧：{video_path}")
    
    video_dir = video_path.parent
    video_basename = video_path.stem
    out_dir = _choose_out_dir(out_root, uploader=video_dir.name, base=video_basename)
    out_dir.mkdir(parents=True, exist_ok=True)

    enhanced_jsonl = (out_dir / "enhanced_captions.jsonl")
    enhanced_f = enhanced_jsonl.open("w", encoding="utf-8")

    total = len(entries) if max_subs <= 0 else min(len(entries), max_subs)
    tprint(f"处理：{video_basename} | 条目 {total}/{len(entries)} | 时长 {duration:.2f}s | 相似度阈值 {similarity_threshold}")

    saved_hashes: Set[str] = set()
    saved_count = 0
    skipped_count = 0
        # === 新增：按每 N 张成功保存的帧切分字幕 ===
    subs_chunks: List[str] = []
    subs_chunk_size = max(0, int(subs_per_chunk))  # 0 表示禁用
    saved_in_current_segment = 0
    segment_start_time: Optional[float] = None
    last_saved_time: Optional[float] = None
    img_info: Optional[Enhancer.ImageInfo] = None
    enh_text: str = ""
    info_str: str = ""
    for idx, e in enumerate(entries[:total], 1):
        safe_end = max(duration - 0.01, 0.0) if duration > 0 else max(e.end, e.start)
        start_time = max(0.0, min(e.start, safe_end))
        end_time = max(0.0, min(e.end, safe_end))
        mid_time = max(0.0, min((start_time + end_time) / 2.0, safe_end))

        # 跳过开头10秒
        if start_time < 12.0:
            continue

        #time_points = [(start_time, "start"), (mid_time, "mid"), (end_time, "end")]
        #for t, frame_type in time_points:
        ts_name = _sec_to_fname_ts(mid_time)
        #fname = f"{ts_name}_{frame_type}.jpg"
        fname = f"{ts_name}.jpg"
        out_img = out_dir / fname

        ok = extract_frame(video_path, mid_time, out_img)
        if not ok and mid_time > 0:
            ok = extract_frame(video_path, max(0.0, mid_time - 0.2), out_img)

        if ok:
            if is_similar_to_previous(out_img, saved_hashes, similarity_threshold):
                out_img.unlink(missing_ok=True)
                skipped_count += 1
                tprint(f"  [skip] 相似帧已跳过：{video_basename} | {fname}")
            else:
                current_hash = calculate_image_hash(out_img)
                if current_hash:
                    saved_hashes.add(current_hash)
                    saved_count += 1
                    tprint(f"  [save] 新帧已保存：{video_basename} | {fname}")
                    # —— 新增：分析当前帧并增强字幕 —— 
                    img_info = enhancer.analyze_image(out_img, current_hash)
                    enh_text, info_str = enhancer.enhance_caption(e.text, img_info)

                    # 以字符串落盘（JSONL：一行一条）


                else:
                    saved_count += 1
                    tprint(f"  [save] 帧已保存（哈希计算失败）：{video_basename} | {fname}")
                                        # === 新增：统计“成功保存的帧”并按 N 张切分字幕 ===
                # 当前帧时间点用于作为本段的“结束处”
                current_frame_time = mid_time
                if segment_start_time is None:
                    # 第一张成功保存的帧，作为本段起点
                    segment_start_time = current_frame_time
                saved_in_current_segment += 1
                last_saved_time = current_frame_time

                # 达到 N 张则切一段
                if subs_chunk_size > 0 and saved_in_current_segment >= subs_chunk_size:
                    chunk_text = collect_subtitles_text(entries, segment_start_time, current_frame_time)
                    if chunk_text:
                        subs_chunks.append(chunk_text)
                    # 下一段从当前帧时间开始
                    segment_start_time = current_frame_time
                    saved_in_current_segment = 0
            
            enhanced_record = {
                "image": str(out_img),
                "start": start_time,
                "end": end_time,
                "subtitle_orig": e.text,
                "subtitle_enhanced": enh_text,
                "image_info": info_str
            }
            enhanced_f.write(json.dumps(enhanced_record, ensure_ascii=False) + "\n")
    # === 新增：补齐尾段（不足 N 张但仍需输出）
    if subs_chunk_size > 0 and segment_start_time is not None and last_saved_time is not None and saved_in_current_segment > 0:
        chunk_text = collect_subtitles_text(entries, segment_start_time, last_saved_time)
        if chunk_text:
            subs_chunks.append(chunk_text)
    tprint(f"  [summary] {video_basename} | 保存 {saved_count} 帧，跳过 {skipped_count} 相似帧")

    return subs_chunks
    # === 新增：写出分段字幕列表到 JSON（与该视频帧同目录）
    # if subs_chunk_size > 0 and write_chunks:
    #     meta = {
    #         "video": str(video_path),
    #         "subtitle": str(subtitle_path),
    #         "subs_per_chunk": subs_chunk_size,
    #         "chunks_count": len(subs_chunks),
    #         "chunks": subs_chunks
    #     }
    #     out_json = out_dir / f"subs_chunks_{subs_chunk_size}.json"
    #     try:
    #         with out_json.open("w", encoding="utf-8") as f:
    #             json.dump(meta, f, ensure_ascii=False, indent=2)
    #         tprint(f"  [subs] 已写出分段字幕：{out_json}")
    #     except Exception as e:
    #         tprint(f"[warn] 写分段字幕失败：{out_json} | {e}")


def load_manifest(manifest_path: Path) -> List[dict]:
    if not manifest_path.exists():
        tprint(f"[warn] manifest 不存在：{manifest_path}")
        return []
    records = []
    with manifest_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                rec = json.loads(line)
                records.append(rec)
            except Exception:
                continue
    return records

# def _default_workers() -> int:
#     # I/O + ffmpeg 子进程为主，适当高于 CPU 数
#     cpu = multiprocessing.cpu_count()
#     return max(2, min(4, cpu))

def main():
    parser = argparse.ArgumentParser(description="按字幕时间戳抽取起始/中点/结束帧（多线程：一视频一线程）")
    parser.add_argument("--manifest", type=str, default=str(DEFAULT_MANIFEST), help="manifest.jsonl 路径")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUTPUT_DIR), help="输出根目录")
    parser.add_argument("--max-subs", type=int, default=0, help="每个视频最多处理的字幕条目数；0=不限制")
    parser.add_argument("--only-video", type=str, default="", help="仅处理匹配此文件名片段的视频（可选）")
    parser.add_argument("--similarity-threshold", type=int, default=5, help="相似度阈值（0-64，越小越严格，默认5）")
   #  parser.add_argument("--workers", type=int, default=_default_workers(), help="并发线程数（一个视频对应一个线程）")
    parser.add_argument("--subs-per-chunk", type=int, default=6, help="每成功保存 N 张图片帧切一段字幕并输出到 JSON；0=不启用")

    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    records = load_manifest(manifest_path)
    if not records:
        tprint("无记录可处理。")
        return

    # 准备任务列表（严格保持“一线程一视频”）
    tasks = []
    for rec in records:
        v = rec.get("video_path")
        s = rec.get("subtitle_path")
        if not v or not s: continue
        vpath = Path(v)
        spath = Path(s)
        process_one_video(vpath, spath, out_root, max_subs=0, similarity_threshold=4, subs_per_chunk = 6)
        
        # if args.only_video and args.only_video not in vpath.name: continue
        # if not vpath.exists() or not spath.exists(): continue
        # tasks.append((vpath, spath))

    if not tasks:
        tprint("无符合条件的视频。")
        return

    # tprint(f"共 {len(tasks)} 个视频，启动并发抽帧：workers={args.workers}")
    futures = []
    # with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
    #     for vpath, spath in tasks:
    #         futures.append(ex.submit(
    #             process_one_video,
    #             vpath, spath, out_root,
    #             args.max_subs, args.similarity_threshold
    #         ))

    #     # 等待全部完成并收集异常
    #     for fut in as_completed(futures):
    #         try:
    #             fut.result()
    #         except Exception as e:
    #             tprint(f"[error] 抽帧线程异常：{e}")

    tprint("全部抽帧任务完成。")

if __name__ == "__main__":
    main()
