from pathlib import Path
import time
import subprocess
import json
from typing import List, Optional, Dict, Any
import glob
import Email_sender

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, ElementClickInterceptedException

CHAT_URL = "https://chatgpt.com/"
PROJECT_ROOT = Path(__file__).resolve().parent
PLUS_BTN = (By.CSS_SELECTOR, "button.composer-btn[data-testid='composer-plus-btn']")
CHROME_PORT = 9222  # Chrome调试端口
CHROME_USER_DATA_DIR = PROJECT_ROOT / "chatgpt-selenium-profile"
STORAGE_DIR = PROJECT_ROOT / "video_storage"
def check_chrome_running(port: int = CHROME_PORT) -> bool:
    """检查指定端口的Chrome是否在运行"""
    try:
        import requests
        response = requests.get(f"http://localhost:{port}/json/version", timeout=2)
        return response.status_code == 200
    except:
        return False

def start_chrome_with_debug(port: int = CHROME_PORT, user_data_dir: str = CHROME_USER_DATA_DIR):
    """启动带调试端口的Chrome"""
    chrome_cmd = [
        "chrome.exe",  # 或者完整路径
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check"
    ]
    try:
        subprocess.Popen(chrome_cmd, shell=True)
        time.sleep(3)  # 等待Chrome启动
        print(f"[DEBUG] 已启动Chrome，调试端口: {port}")
    except Exception as e:
        print(f"[ERROR] 启动Chrome失败: {e}")
        raise

def launch_browser(use_existing_profile=True) -> webdriver.Chrome:
    """启动或接管Chrome浏览器"""
    # 1. 检查是否有Chrome在运行
    if not check_chrome_running(CHROME_PORT):
        print("[DEBUG] 未检测到运行中的Chrome，启动新的Chrome实例...")
        start_chrome_with_debug(CHROME_PORT, CHROME_USER_DATA_DIR)
        time.sleep(5)  # 等待Chrome完全启动
    
    # 2. 连接到已运行的Chrome
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"localhost:{CHROME_PORT}")
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
        driver.set_window_size(1280, 900)
        print("[DEBUG] 成功连接到Chrome")
        return driver
    except Exception as e:
        print(f"[ERROR] 连接Chrome失败: {e}")
        raise


def wait_for_login(driver: webdriver.Chrome, timeout=180):
    driver.get(CHAT_URL)
    # 简单策略：等待输入框或“新建对话”之类元素出现；否则给你时间手动完成登录
    try:
        WebDriverWait(driver, timeout).until_any(
            [
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#prompt-textarea.ProseMirror[contenteditable='true']")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "textarea, [contenteditable='true']")),
                EC.presence_of_element_located((By.XPATH, "//button[contains(., 'New chat') or contains(., '新建对话')]")),
            ]
        )
    except Exception:
        print("登录可能尚未完成，请检查浏览器窗口并登录后再运行脚本。")
        raise

# 给 WebDriverWait 增加一个小工具：直到任一条件满足
def _until_any_patch():
    def until_any(self, conditions, message=''):
        last_exc = None
        for _ in range(int(self._timeout / self._poll)):
            for cond in conditions:
                try:
                    value = cond(self._driver)
                    if value:
                        return value
                except Exception as e:
                    last_exc = e
            time.sleep(self._poll)
        if last_exc:
            raise last_exc
        raise TimeoutError(message)
    WebDriverWait.until_any = until_any


_until_any_patch()

def find_prompt_box(driver: webdriver.Chrome):
    # ChatGPT 网页经常调整 DOM，这里给出多种兜底选择器
    candidates = [
        (By.CSS_SELECTOR, "div#prompt-textarea.ProseMirror[contenteditable='true']"),
        (By.CSS_SELECTOR, "textarea[aria-label*='Message'], textarea"),
        (By.CSS_SELECTOR, "div[contenteditable='true']"),
    ]
    for by, sel in candidates:
        els = driver.find_elements(by, sel)
        if els:
            return els[0]
    raise RuntimeError("未找到输入框，请检查页面结构是否更新。")

def click_attach_button(driver, timeout=20, attempts=6):
    for i in range(attempts):
        try:
            # 每一轮都重新定位，避免用旧的元素引用
            WebDriverWait(driver, timeout).until(EC.presence_of_element_located(PLUS_BTN))
            WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(PLUS_BTN))
            btn = driver.find_element(*PLUS_BTN)

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            try:
                btn.click()
            except ElementClickInterceptedException:
                # 有遮挡：先清理悬浮层/菜单，再用 JS 兜底
                driver.execute_script("document.body.click();")
                driver.execute_script("arguments[0].click();", btn)

            return  # 成功
        except StaleElementReferenceException:
            # 元素被替换了：等旧元素完全“陈旧”，再重拿
            try:
                WebDriverWait(driver, 2).until(EC.staleness_of(btn))
            except Exception:
                pass
            continue
        except TimeoutException:
            if i == attempts - 1:
                raise
    raise TimeoutException("点击加号按钮失败：多次出现 stale/遮挡。")
def _click_upload_menuitem_if_any(driver, timeout=5):
    """
    某些版本需要先在弹出的菜单里点“上传文件”，input 才会出现。
    找不到就忽略，继续走 input 探测。
    """
    end = time.time() + timeout
    menuitem_locators = [
        (By.XPATH, "//div[@role='menu']//div[contains(., 'Upload')]"),
        (By.XPATH, "//div[@role='menu']//div[contains(., '文件')]"),
        (By.XPATH, "//button[contains(., 'Upload') or contains(., '文件')]"),
    ]
    while time.time() < end:
        for by, sel in menuitem_locators:
            els = driver.find_elements(by, sel)
            if els:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", els[0])
                    try:
                        els[0].click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", els[0])
                    return
                except StaleElementReferenceException:
                    pass
        time.sleep(0.15)

def find_file_input(driver: webdriver.Chrome):
    #  有的版本需要点“上传文件”菜单
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if inputs:
        return inputs[0]
    # 偶尔在菜单项弹出后才挂载，稍等再找
    _click_upload_menuitem_if_any(driver, timeout=5)
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
    )
    return driver.find_element(By.CSS_SELECTOR, "input[type='file']")


def upload_files(driver, file_paths: List[str], per_file_wait=180):
    """
    点加号 →（必要时）点菜单项 → 找到 input → send_keys 路径 → 等待附件气泡出现。
    """
    # 0) 先做路径存在性检查，避免把不存在的文件传给 Selenium
    abs_list = []
    for p in file_paths:
        ap = Path(p).resolve()
        if not ap.exists():
            raise FileNotFoundError(f"待上传文件不存在：{ap}")
        abs_list.append(str(ap))

    # 1) 打开上传入口
    click_attach_button(driver)

    # 2) 找到真正的 <input type="file">
    file_input = find_file_input(driver)

    # 3) 发送多个路径（Windows 需用 \n 连接）
    joined = "\n".join(abs_list)
    try:
        file_input.send_keys(joined)
    except Exception:
        # 某些实现把 input 隐藏；先强制显示再发一次
        driver.execute_script("arguments[0].style.display='block'; arguments[0].style.visibility='visible';", file_input)
        file_input.send_keys(joined)

    # 4) 按文件名等待“附件气泡/标签”出现，确认加入成功
    for ap in abs_list:
        name = Path(ap).name
        try:
            WebDriverWait(driver, per_file_wait).until(
                EC.any_of(
                    EC.presence_of_element_located((By.XPATH, f"//*[contains(@data-testid,'attachment') and contains(., '{name}')]")),
                    EC.presence_of_element_located((By.XPATH, f"//*[contains(@class,'attachment') and contains(., '{name}')]")),
                    EC.presence_of_element_located((By.XPATH, f"//*[text()[contains(., '{name}')]]")),
                )
            )
        except TimeoutException:
            print(f"[警告] 超时未确认到附件：{name}（可能 UI 文案变更或仍在队列）。继续后续流程。")
    time.sleep(10)

def send_prompt_and_wait(driver: webdriver.Chrome, prompt: str, reply_timeout=300) -> str:
    box = find_prompt_box(driver)
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", box)
    except Exception:
        pass
    box.click()
    is_div_editable = (box.tag_name.lower() == "div" and (box.get_attribute("contenteditable") or "").lower() == "true")
    if is_div_editable:
        try:
            box.send_keys(Keys.CONTROL, "a")
            box.send_keys(Keys.BACKSPACE)
        except Exception:
            pass
    else:
        if box.tag_name.lower() == "textarea":
            try:
                box.clear()
            except Exception:
                pass
    box.send_keys(prompt)
    print(f"[DEBUG] 已输入文本: {prompt[:50]}...")

    # 等待一下确保文本已输入
    time.sleep(10)
    
    # 发送（优先按钮，失败回车兜底）
    send_btn_candidates = [
        (By.CSS_SELECTOR, "button[data-testid='send-button']"),
        (By.CSS_SELECTOR, "button.composer-btn[data-testid='composer-send-button']"),
        (By.CSS_SELECTOR, "button[aria-label*='Send'], button[aria-label*='发送']"),
        (By.CSS_SELECTOR, "button[title*='Send'], button[title*='发送']"),
        (By.XPATH, "//button[contains(., '发送') or contains(., 'Send')]"),
        (By.XPATH, "//button[.//svg[contains(@class, 'send') or contains(@class, 'paper')]]"),
    ]
    sent = False
    for by, sel in send_btn_candidates:
        els = driver.find_elements(by, sel)
        if els:
            btn = els[0]
            print(f"[DEBUG] 找到发送按钮: {sel}")
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.5)
            except Exception:
                pass
            
            # 检查按钮是否可用
            disabled = btn.get_attribute("disabled") or btn.get_attribute("aria-disabled")
            if disabled and str(disabled).lower() in ("true", "disabled"):
                print(f"[DEBUG] 按钮被禁用，跳过: {sel}")
                continue
                
            try:
                btn.click()
                print(f"[DEBUG] 成功点击发送按钮: {sel}")
                sent = True
                break
            except Exception as e:
                print(f"[DEBUG] 点击失败，尝试JS点击: {e}")
                try:
                    driver.execute_script("arguments[0].click();", btn)
                    print(f"[DEBUG] JS点击成功: {sel}")
                    sent = True
                    break
                except Exception as e2:
                    print(f"[DEBUG] JS点击也失败: {e2}")
                    continue
    
    if not sent:
        print("[DEBUG] 所有按钮都失败，尝试回车发送")
        try:
            # 先确保焦点在输入框
            box.click()
            time.sleep(0.5)
            # 尝试不同的回车方式
            box.send_keys(Keys.ENTER)
            print("[DEBUG] 回车发送成功")
            sent = True
        except Exception as e:
            print(f"[DEBUG] 回车发送失败: {e}")
            try:
                # 最后尝试 Ctrl+Enter
                box.send_keys(Keys.CONTROL, Keys.ENTER)
                print("[DEBUG] Ctrl+Enter发送成功")
                sent = True
            except Exception as e2:
                print(f"[DEBUG] Ctrl+Enter也失败: {e2}")
    
    if not sent:
        print("[ERROR] 所有发送方式都失败了！")
        return "（发送失败：无法找到或点击发送按钮）"

    print("[DEBUG] 等待GPT回复...")
    try:
        msg = WebDriverWait(driver, reply_timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-message-author-role='assistant']"))
        )
    except Exception:
        return "（超时：未等到模型回复）"
    time.sleep(30)
    msgs = driver.find_elements(By.CSS_SELECTOR, "[data-message-author-role='assistant']")
    last = msgs[-1]
    return last.text

def run_get_reply(prompt: str, files: List[str]) -> str:
    """发送文件到GPT并获取回复"""
    driver = launch_browser(use_existing_profile=True)
    try:
        wait_for_login(driver, timeout=180)
        driver.get(CHAT_URL)
        upload_files(driver, files)
        reply = send_prompt_and_wait(driver, prompt)
        return reply
    except Exception as e:
        print(f"[ERROR] GPT交互失败: {e}")
        return f"（错误：{e}）"
    finally:
        # 不关闭浏览器，保持连接
        pass

def find_video_results(results_file: str = STORAGE_DIR / "results.jsonl") -> List[Dict[str, Any]]:
    """从results.jsonl读取记录，查找所有视频处理结果（包含txt和zip的目录）"""
    results = []
    results_path = Path(results_file)
    
    if not results_path.exists():
        print(f"[WARN] results文件不存在: {results_file}")
        return results
    
    # 读取results.jsonl
    records = []
    try:
        with results_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    records.append(record)
                except json.JSONDecodeError:
                    continue
        print(f"[INFO] 从results.jsonl读取到 {len(records)} 条记录")
    except Exception as e:
        print(f"[ERROR] 读取results.jsonl失败: {e}")
        return results
    
    # 处理每条记录
    for record in records:
        video_folder = record.get("video_folder")
        files = record.get("files", [])
        
        if not video_folder or not files:
            continue
            
        video_folder_path = Path(video_folder)
        if not video_folder_path.exists():
            print(f"[WARN] 视频目录不存在: {video_folder}")
            continue
        
        # 从文件路径中提取信息
        zip_file = None
        txt_file = None
        
        for file_path in files:
            file_path_obj = Path(file_path)
            if file_path_obj.suffix.lower() == ".zip":
                zip_file = str(file_path_obj)
            elif file_path_obj.suffix.lower() == ".txt":
                txt_file = str(file_path_obj)
        
        # 只处理同时有txt和zip的记录
        if txt_file and zip_file:
            # 从目录路径提取作者和视频名
            # 路径格式: E:/coin_works/project/video_storage/作者/视频名
            path_parts = video_folder_path.parts
            if len(path_parts) >= 4:
                author = path_parts[-2]  # 倒数第二个是作者
                video_name = path_parts[-1]  # 倒数第一个是视频名
            else:
                author = "unknown"
                video_name = video_folder_path.name
            
            result = {
                "author": author,
                "video_dir": str(video_folder_path),
                "txt_file": txt_file,
                "zip_file": zip_file,
                "video_name": video_name,
                "files": files
            }
            results.append(result)
            print(f"[INFO] 找到结果: {author}/{video_name}")
        else:
            print(f"[WARN] 记录缺少必要文件: {video_folder} (txt: {txt_file}, zip: {zip_file})")
    
    return results
def batch_process_to_gpt(prompt_template: str, output_file: str = "gpt_replies.txt"):
    """批量处理所有视频结果到GPT"""
    results = find_video_results()
    
    if not results:
        print("[WARN] 没有找到任何视频处理结果")
        return
    
    print(f"[INFO] 找到 {len(results)} 个视频结果，开始批量处理...")
    
    # 创建输出文件
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("=== GPT批量回复结果 ===\n\n")
    
    for i, result in enumerate(results, 1):
        print(f"\n[INFO] 处理第 {i}/{len(results)} 个: {result['author']}/{result['video_name']}")
        
        try:
            # 构建prompt
            prompt = prompt_template.format(
                title=result['video_name'],
                uploader=result['author'],
                video_path=result['video_dir']
            )
            
            # 准备文件
            files = [result['txt_file'], result['zip_file']]
            
            # 发送到GPT
            reply = run_get_reply(prompt, files)
            
            # 保存结果到文件
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(f"【{i}/{len(results)}】{result['author']} - {result['video_name']}\n")
                f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Prompt: {prompt}\n")
                f.write(f"GPT回复:\n{reply}\n")
                f.write("-" * 80 + "\n\n")
            
            print(f"[SUCCESS] 完成: {result['video_name']}")
            
            # 避免请求过快
            time.sleep(5)
            
        except Exception as e:
            print(f"[ERROR] 处理失败 {result['video_name']}: {e}")
            # 记录错误信息
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(f"【{i}/{len(results)}】{result['author']} - {result['video_name']}\n")
                f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"错误: {e}\n")
                f.write("-" * 80 + "\n\n")
            continue
    
    print(f"\n[SUCCESS] 批量处理完成！共处理 {len(results)} 个视频")
    
    print(f"[INFO] 结果已保存到: {output_file}")

def run(prompt: str, files: List[str]):
    """单次运行（保持原有接口）"""
    reply = run_get_reply(prompt, files)
    Email_sender.main(reply)
    print("\n=== 模型回复（截取） ===\n")
    print(reply[:2000])

if __name__ == "__main__":
    # 示例：把一个 txt 和一个 zip 一起发给 ChatGPT，并附上引导 prompt
    prompt_text = (
        "你是一位加密货币短线交易博主，擅长用简洁但专业的口吻，在社交媒体上分析市场走势。 "
        "请根据我提供的压缩文件中的图片和字幕结合当前时间，生成一篇市场点评，要求： "
        "1. **角色设定** - 你是经验丰富的交易员，熟悉 BTC/ETH 等主流币的技术面分析。 - 擅长用通俗的交易术语解释复杂走势，让读者快速理解市场逻辑。"
        "2. **结构要求** - 开头点出市场主线或主要操作思路（如“今天主力在进行双头清算”）。 - 按时间或逻辑顺序描述关键价格位置、突破/回落动作。 - 提及具体的关键点位（支撑位、阻力位）、K线周期（1小时、日K等）。 - 对未来可能的走势进行简短判断，并给出风险提示。 "
        "3. **语言风格** - 用交易圈常用词（如“清算”“支撑线”“阻力”“回踩”“突破”）。 - 口吻偏直接、判断明确，但不做绝对承诺。 - 句子多用短句，加入数字、价格位、时间点（突出数字点位）。 - 偶尔用括号补充说明。 "
        "4. **输出格式** - 不要分标题段落，保持社交媒体一段话的流畅阅读感。 - 文末可附一句简短总结或提醒。 "

    )
    # files_to_send = [
    #     r"E:\coin_works\project\video_storage\DA 交易者聯盟\2025-08-22-DA交易者聯盟-1\2025-08-22-DA交易者聯盟-1.txt",    # 改成你的绝对路径
    #     r"E:\coin_works\project\video_storage\DA 交易者聯盟\2025-08-22-DA交易者聯盟-1\frames.zip",  # 改成你的绝对路径
    # ]
    batch_process_to_gpt(prompt_text)
