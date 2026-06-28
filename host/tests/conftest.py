# -*- coding: utf-8 -*-
"""pytest conftest"""
import sys
from pathlib import Path

# 添加项目根目录到路径，使 `import src.xxx` 可用
sys.path.insert(0, str(Path(__file__).parent.parent))
