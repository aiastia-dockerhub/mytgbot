# ==================== 阶段1: 编译 ====================
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Cython 和项目依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir cython setuptools

# 复制源码
COPY . .

# 编译所有 .py → .so（除 main.py 和 build.py）
RUN python build.py build_ext --inplace 2>&1

# 清理编译产物中的 .c 文件，只保留 .so
RUN find . -name "*.c" -delete && \
    find . -name "*.py" ! -name "main.py" ! -path "./build_temp/*" -delete && \
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true

# ==================== 阶段2: 运行 ====================
FROM python:3.11-slim

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# 只安装运行时依赖（不需要 Cython）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 从 builder 阶段复制编译好的 .so 文件和 main.py
COPY --from=builder /build/main.py .
COPY --from=builder /build/*.so* ./

RUN mkdir -p /app/data

VOLUME ["/app/data"]

CMD ["python", "main.py"]