# x-agent 每日新闻智能体

## 📋 项目概述
通过从多个内容平台采集相关热门关键词信息，进行去重、质量评估与热点聚合，输出结构化新闻简报，并通过调整skills和mcp实现不同的新闻简报。



### 核心功能

- 📊 **推特数据抓取**: 自动抓取相关笔记和评论数据（使用用户输入作为搜索关键词，已移除关键词生成功能）
- 🤖 **AI 内容分析**: 使用 LLM 分析用户痛点和市场需求
- 📄 **自动化报告生成**: 生成专业的每日新闻报告
### 快速开始

```bash
# 安装依赖
cd src
pip install -r requirements.txt

# 配置 API 密钥 (编辑 src/.env 文件)
# OPENAI_API_KEY=your_key
# TIKHUB_TOKEN=your_token

# 运行验证
python run_agent.py skills
```
