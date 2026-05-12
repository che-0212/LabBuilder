"""
文件工具
提供JSON加载、图片加载、base64编码等功能
"""

import json
import os
import base64
from typing import Dict, List, Optional
from pathlib import Path


def load_json(file_path: str) -> Dict:
    """
    加载JSON文件
    
    Args:
        file_path: JSON文件路径
    
    Returns:
        data: JSON数据字典
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"无法加载JSON文件 {file_path}: {e}")


def save_json(data: Dict, file_path: str, indent: int = 2):
    """
    保存JSON文件
    
    Args:
        data: 要保存的数据
        file_path: 保存路径
        indent: 缩进空格数
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
    except Exception as e:
        raise RuntimeError(f"无法保存JSON文件 {file_path}: {e}")


def load_image_as_base64(image_path: str) -> Optional[str]:
    """
    加载图片并编码为base64
    
    Args:
        image_path: 图片路径
    
    Returns:
        base64_str: base64编码的字符串
    """
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
            return base64.b64encode(image_data).decode('utf-8')
    except Exception as e:
        print(f"警告: 无法加载图片 {image_path}: {e}")
        return None


def find_experiment_images(images_base_dir: str, experiment_name: str, 
                          views: List[str], image_format: str = 'png') -> Dict[str, str]:
    """
    查找实验的渲染图片
    
    Args:
        images_base_dir: 图片基础目录
        experiment_name: 实验名称（可以为None，直接在base_dir查找）
        views: 视图列表
        image_format: 图片格式
    
    Returns:
        image_paths: {view_name: image_path}
    """
    image_paths = {}
    
    # 首先尝试在子目录中查找
    experiment_dir = os.path.join(images_base_dir, experiment_name)
    if os.path.exists(experiment_dir) and os.path.isdir(experiment_dir):
        for view in views:
            image_path = os.path.join(experiment_dir, f"{view}.{image_format}")
            if os.path.exists(image_path):
                image_paths[view] = image_path
    
    # 如果子目录中没找到，直接在base_dir中查找
    if len(image_paths) == 0:
        print(f"在子目录 {experiment_dir} 中未找到图片，尝试在基础目录中查找...")
        for view in views:
            image_path = os.path.join(images_base_dir, f"view_{view}.{image_format}")
            if os.path.exists(image_path):
                image_paths[view] = image_path
                print(f"找到图片: {image_path}")
    
    if len(image_paths) == 0:
        print(f"警告: 未找到任何渲染图片")
    
    return image_paths


def ensure_dir(directory: str):
    """确保目录存在"""
    os.makedirs(directory, exist_ok=True)


def get_output_paths(output_dir: str, experiment_name: str) -> Dict[str, str]:
    """
    生成输出文件路径
    
    Args:
        output_dir: 输出目录
        experiment_name: 实验名称
    
    Returns:
        paths: 包含各种输出文件路径的字典
    """
    ensure_dir(output_dir)
    
    # 清理文件名中的非法字符（括号、冒号等）
    safe_name = experiment_name.replace('(', '_').replace(')', '_').replace(':', '_').replace('/', '_').replace('\\', '_')
    # 移除多余的下划线
    safe_name = '_'.join(filter(None, safe_name.split('_')))
    
    return {
        'json_report': os.path.join(output_dir, f"{safe_name}_evaluation_report.json"),
        'html_report': os.path.join(output_dir, f"{safe_name}_evaluation_report.html"),
        'questions': os.path.join(output_dir, f"{safe_name}_questions.json"),
        'log': os.path.join(output_dir, f"{safe_name}_evaluation.log")
    }

