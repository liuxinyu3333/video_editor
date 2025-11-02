# YouTube视频处理与GPT分析项目

这是一个自动化YouTube视频下载、抽帧处理并通过GPT生成分析报告的项目。

## 🚀 快速开始

### 方法一：一键部署（推荐）

```bash
# 1. 克隆项目
git clone <your-repo-url>
cd project

# 2. 运行自动部署脚本
python setup.py
```

### 方法二：手动部署

```bash
# 1. 安装Python依赖
pip install -r requirements.txt

# 2. 创建必要目录
mkdir video_storage frames_output yt-dlp chatgpt-selenium-profile

# 3. 下载yt-dlp
# Windows: 下载yt-dlp.exe到yt-dlp/目录
# Linux/Mac: 下载yt-dlp到yt-dlp/目录并添加执行权限

# 4. 安装FFmpeg
# Windows: 下载并添加到PATH
# Linux: sudo apt install ffmpeg
# Mac: brew install ffmpeg

# 5. 安装Chrome浏览器
```

## 📋 系统要求

- **Python**: 3.8+ (推荐3.9+)
- **操作系统**: Windows/Linux/macOS
- **FFmpeg**: 用于视频处理
- **Chrome浏览器**: 用于Selenium自动化
- **内存**: 至少4GB RAM
- **存储**: 至少10GB可用空间

## ⚙️ 配置说明

### 1. YouTube Cookies配置

编辑 `cookies.txt` 文件，添加你的YouTube cookies：

```
# 格式: domain	flag	path	secure	expiration	name	value
.youtube.com	TRUE	/	FALSE	1234567890	PREF	...
```

### 2. 邮箱配置

编辑 `.env` 文件或直接修改 `Email_sender.py`：

```python
# QQ邮箱配置
MAIL_USER = "your-email@qq.com"
MAIL_PASS = "your-app-password"  # 不是QQ密码，是授权码
```

### 3. 路径配置

修改 `video_loader.py` 中的路径：

```python
SAVE_DIR = r"你的项目路径/video_storage"
FFMPEG_BIN_DIR = r"你的ffmpeg安装路径/bin"
COOKIE_FILE = r"你的cookies文件路径/cookies.txt"
```

## 🎯 使用方法

### 运行完整流程

```bash
python pipeline.py
```

### 运行单个组件

```bash
# 只下载视频
python video_loader.py

# 只处理抽帧
python video_cut.py

# 只发送到GPT
python upload_to_gpt.py

# 只发送邮件
python Email_sender.py
```

## 📁 项目结构

```
project/
├── pipeline.py              # 主流程控制
├── video_loader.py          # YouTube视频下载
├── video_cut.py            # 视频抽帧处理
├── upload_to_gpt.py        # GPT交互
├── Email_sender.py         # 邮件发送
├── requirements.txt        # Python依赖
├── setup.py               # 自动部署脚本
├── README.md              # 项目说明
├── video_storage/         # 视频存储目录
├── frames_output/         # 抽帧输出目录
├── yt-dlp/               # yt-dlp可执行文件
└── chatgpt-selenium-profile/  # Chrome用户数据
```

## 🔧 功能特性

- **自动下载**: 从指定YouTube频道下载最新视频
- **智能抽帧**: 根据字幕时间戳提取关键帧
- **去重处理**: 自动识别并跳过相似帧
- **GPT分析**: 自动上传文件到ChatGPT并获取分析
- **邮件发送**: 自动发送结果到指定邮箱
- **批量处理**: 支持多视频批量处理
- **错误处理**: 完善的错误处理和重试机制

## 🐛 常见问题

### 1. FFmpeg未找到
```bash
# Windows: 下载FFmpeg并添加到PATH
# 或在video_loader.py中指定完整路径

# Linux
sudo apt update && sudo apt install ffmpeg

# Mac
brew install ffmpeg
```

### 2. Chrome浏览器问题
- 确保Chrome浏览器已安装
- 检查Chrome版本是否与Selenium兼容
- 如果遇到验证码，需要手动完成验证

### 3. YouTube下载失败
- 检查cookies.txt文件是否正确
- 确认网络连接正常
- 尝试更新yt-dlp版本

### 4. 邮件发送失败
- 检查邮箱配置是否正确
- 确认使用的是授权码而不是密码
- 检查网络连接和防火墙设置

## 📝 开发说明

### 添加新的YouTube频道

在 `video_loader.py` 中修改 `SOURCES` 列表：

```python
SOURCES = [
    "https://www.youtube.com/@YourChannel",
    # 添加更多频道...
]
```

### 自定义GPT提示词

在 `pipeline.py` 中修改 `prompt_text` 变量：

```python
prompt_text = "你的自定义提示词..."
```

### 调整抽帧参数

在 `video_cut.py` 中修改参数：

```python
similarity_threshold = 5  # 相似度阈值，越小越严格
max_subs = 0  # 最大字幕条目数，0表示不限制
```

## 📄 许可证

本项目仅供学习和研究使用，请遵守相关法律法规和平台服务条款。

## 🤝 贡献

欢迎提交Issue和Pull Request来改进项目。

## 📞 支持

如果遇到问题，请：

1. 查看本文档的常见问题部分
2. 检查项目的Issue页面
3. 创建新的Issue描述问题

