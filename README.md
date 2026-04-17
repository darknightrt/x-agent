# 安装依赖
cd src
pip install -r requirements.txt

# 配置 API 密钥 (编辑 src/.env 文件)
# OPENAI_API_KEY=your_key
# TIKHUB_TOKEN=your_token

# 运行验证
python run_agent.py skills
