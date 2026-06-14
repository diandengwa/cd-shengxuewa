# K12 Rocket v2.0 - 点灯蛙·成都K12升学参谋 Dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装必要的依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 复制代码
COPY . .

# 创建必要的运行目录
RUN mkdir -p data logs feedback static templates

# 暴露接口端口
EXPOSE 8000

# 运行 FastAPI 应用
CMD ["python", "-m", "app.main"]
