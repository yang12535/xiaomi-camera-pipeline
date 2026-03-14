# 贡献指南

## 开发环境

```bash
# 克隆项目
git clone https://github.com/yang12535/xiaomi-camera-pipeline.git
cd xiaomi-camera-pipeline

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

## 代码规范

### 编码规范

- **编码**: 必须使用 UTF-8（无 BOM）
- **换行符**: 必须使用 LF（Unix 风格）
- **缩进**: 4 个空格
- **行宽**: 不超过 100 字符

### Python 规范

遵循 PEP 8，重要规则：

```python
# 文件头
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 导入顺序
import os          # 标准库
import sys

import yaml        # 第三方库

from mymodule import func  # 本地模块

# 函数文档字符串
def my_function(param1, param2):
    """简短描述。
    
    详细描述...
    
    Args:
        param1: 参数1说明
        param2: 参数2说明
        
    Returns:
        返回值说明
    """
    pass
```

### 提交规范

```
<type>(<scope>): <subject>

<body>

<footer>
```

类型：
- `feat`: 新功能
- `fix`: 修复
- `docs`: 文档
- `style`: 格式（不影响代码运行）
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试
- `chore`: 构建/工具

示例：
```
feat(upload): 添加断点续传功能

- 使用 SQLite 记录上传进度
- 支持自动重试机制
- 添加进度显示

Fixes #123
```

## 提交前检查

```bash
# 检查编码
file pipeline.py  # 应显示 "UTF-8"

# 检查换行符
cat -A pipeline.py | head -5  # 应显示 $（LF），而非 ^M$（CRLF）

# 语法检查
python3 -m py_compile pipeline.py

# 测试运行
python3 pipeline.py
```

## Windows 开发者注意

### 避免 GBK 乱码

1. **VS Code 设置**:
   ```json
   {
     "files.encoding": "utf8",
     "files.eol": "\n"
   }
   ```

2. **Git 配置**:
   ```bash
   git config --global core.autocrlf false
   git config --global core.eol lf
   ```

3. **PowerShell**（如果需要）:
   ```powershell
   [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
   ```

## 版本号规则

遵循 [Semantic Versioning](https://semver.org/):

- `MAJOR.MINOR.PATCH`
- MAJOR: 不兼容的 API 修改
- MINOR: 向下兼容的功能新增
- PATCH: 向下兼容的问题修复

## 发布流程

1. 更新 `VERSION` 文件
2. 更新 `CHANGELOG.md`
3. 创建 Git tag: `git tag v1.x.x`
4. 推送: `git push && git push --tags`
