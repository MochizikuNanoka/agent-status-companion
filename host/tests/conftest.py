# -*- coding: utf-8 -*-
"""pytest conftest"""
import sys
from pathlib import Path

# 确保 src 在路径中
sys.path.insert(0, str(Path(__file__).parent / "src"))
