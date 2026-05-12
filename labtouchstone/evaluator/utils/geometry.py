"""
几何计算工具
提供距离计算、碰撞检测、边界检查等几何操作
"""

import math
from typing import Dict, List, Tuple, Optional


def calculate_distance_2d(pos1: Dict[str, float], pos2: Dict[str, float]) -> float:
    """
    计算两个位置的2D欧氏距离（忽略Z轴）
    
    Args:
        pos1: {'x': float, 'y': float, 'z': float}
        pos2: {'x': float, 'y': float, 'z': float}
    
    Returns:
        distance: 距离（cm）
    """
    dx = pos1['x'] - pos2['x']
    dy = pos1['y'] - pos2['y']
    return math.sqrt(dx**2 + dy**2) * 100  # 转换为cm


def rotate_bbox(bbox: Dict[str, float], rotation_z: float) -> Tuple[float, float]:
    """
    根据旋转角度计算物体实际占用的AABB尺寸（轴对齐包围盒）
    
    此函数与布局生成器的旋转逻辑保持一致（layout_engine_v3.py）
    
    Args:
        bbox: {'x': short, 'y': long, 'z': height} 或 {'short': ..., 'long': ..., 'height': ...}
              其中 short=短边, long=长边 (单位：米)
        rotation_z: 绕 Z 轴旋转角度（度）
    
    Returns:
        (x_size, y_size): 旋转后物体在 X, Y 方向的实际占用尺寸（米）
    
    旋转规则（与实际资产朝向一致）：
        - 0°：面向+Y（北），长边平行于X轴 → X方向 = long, Y方向 = short
        - 90°：面向-X（西），长边平行于Y轴 → X方向 = short, Y方向 = long
        - 180°：面向-Y（南），长边平行于X轴 → X方向 = long, Y方向 = short
        - 270°：面向+X（东），长边平行于Y轴 → X方向 = short, Y方向 = long
    """
    # 兼容不同的bbox格式
    if 'short' in bbox and 'long' in bbox:
        # 新格式: {short, long, height}
        short = bbox['short']
        long = bbox['long']
    elif 'x' in bbox:
        # 旧格式: {x, y, z} 其中 x=short, y=long
        short = bbox['x']
        long = bbox['y']
    elif 'width' in bbox:
        # 兼容更旧的格式（不应该出现）
        short = bbox['width']
        long = bbox['depth']
    else:
        # 默认值
        short = 0.1
        long = 0.1
    
    # 根据旋转角度判断实际占用的XY尺寸
    rotation_normalized = rotation_z % 360
    if rotation_normalized in [90, 270, -90, -270]:
        # 旋转90度或270度：长边平行于Y轴 → X方向 = short, Y方向 = long
        x_size = short
        y_size = long
    else:
        # 旋转0度或180度：长边平行于X轴 → X方向 = long, Y方向 = short
        x_size = long
        y_size = short

    
    return x_size, y_size


def check_bbox_overlap(obj1_pos: Dict, obj1_bbox: Dict, obj1_rotation: float,
                       obj2_pos: Dict, obj2_bbox: Dict, obj2_rotation: float) -> Tuple[bool, float]:
    """
    检查两个物体的包围盒是否重叠（使用精确的3D AABB碰撞检测）
    
    Args:
        obj1_pos: 物体1中心位置 {'x', 'y', 'z'}
        obj1_bbox: 物体1包围盒 {'x': short, 'y': long, 'z': height} 或 {'short': ..., 'long': ..., 'height': ...}
        obj1_rotation: 物体1旋转角度（度）
        obj2_pos: 物体2中心位置
        obj2_bbox: 物体2包围盒
        obj2_rotation: 物体2旋转角度（度）
    
    Returns:
        (is_overlap, overlap_distance): 是否重叠，重叠距离（负值表示重叠，单位：米）
    """
    # 计算旋转后的AABB尺寸 (x_size = X方向占用, y_size = Y方向占用)
    x_size1, y_size1 = rotate_bbox(obj1_bbox, obj1_rotation)
    x_size2, y_size2 = rotate_bbox(obj2_bbox, obj2_rotation)
    
    # 获取Z轴高度（从bbox中获取，默认0.2m）
    z_size1 = obj1_bbox.get('z', obj1_bbox.get('height', 0.2))
    z_size2 = obj2_bbox.get('z', obj2_bbox.get('height', 0.2))
    
    # 计算各物体的3D AABB边界（Axis-Aligned Bounding Box）
    obj1_x_min = obj1_pos['x'] - x_size1 / 2
    obj1_x_max = obj1_pos['x'] + x_size1 / 2
    obj1_y_min = obj1_pos['y'] - y_size1 / 2
    obj1_y_max = obj1_pos['y'] + y_size1 / 2
    obj1_z_min = obj1_pos['z'] - z_size1 / 2
    obj1_z_max = obj1_pos['z'] + z_size1 / 2
    
    obj2_x_min = obj2_pos['x'] - x_size2 / 2
    obj2_x_max = obj2_pos['x'] + x_size2 / 2
    obj2_y_min = obj2_pos['y'] - y_size2 / 2
    obj2_y_max = obj2_pos['y'] + y_size2 / 2
    obj2_z_min = obj2_pos['z'] - z_size2 / 2
    obj2_z_max = obj2_pos['z'] + z_size2 / 2
    
    # 3D AABB碰撞检测：检查两个物体是否在X、Y、Z三个方向都有重叠
    # 使用严格不等式，添加1mm容差，避免边界接触被误判为碰撞
    tolerance = 0.001  # 1mm容差
    overlap_x = not (obj1_x_max <= obj2_x_min + tolerance or obj1_x_min >= obj2_x_max - tolerance)
    overlap_y = not (obj1_y_max <= obj2_y_min + tolerance or obj1_y_min >= obj2_y_max - tolerance)
    overlap_z = not (obj1_z_max <= obj2_z_min + tolerance or obj1_z_min >= obj2_z_max - tolerance)
    is_overlap = overlap_x and overlap_y and overlap_z
    
    # 计算重叠距离（用于兼容旧接口）
    if not is_overlap:
        # 计算最小间隙（3D）
        x_gap = min(abs(obj1_x_min - obj2_x_max), abs(obj2_x_min - obj1_x_max))
        y_gap = min(abs(obj1_y_min - obj2_y_max), abs(obj2_y_min - obj1_y_max))
        z_gap = min(abs(obj1_z_min - obj2_z_max), abs(obj2_z_min - obj1_z_max))
        overlap_distance = min(x_gap, y_gap, z_gap)  # 正值表示无碰撞
    else:
        # 计算重叠深度（负值表示重叠，3D）
        x_overlap = min(obj1_x_max - obj2_x_min, obj2_x_max - obj1_x_min)
        y_overlap = min(obj1_y_max - obj2_y_min, obj2_y_max - obj1_y_min)
        z_overlap = min(obj1_z_max - obj2_z_min, obj2_z_max - obj1_z_min)
        overlap_distance = -min(x_overlap, y_overlap, z_overlap)  # 负值
    
    return is_overlap, overlap_distance


def calculate_overlap_area(obj1_pos: Dict, obj1_bbox: Dict, obj1_rotation: float,
                          obj2_pos: Dict, obj2_bbox: Dict, obj2_rotation: float) -> float:
    """
    计算重叠面积（使用精确的3D AABB重叠体积，返回为cm²单位以兼容旧接口）
    
    Args:
        同 check_bbox_overlap
    
    Returns:
        overlap_area: 重叠面积（cm²，实际为X-Y平面投影面积）
    """
    # 计算旋转后的AABB尺寸 (x_size = X方向占用, y_size = Y方向占用)
    x_size1, y_size1 = rotate_bbox(obj1_bbox, obj1_rotation)
    x_size2, y_size2 = rotate_bbox(obj2_bbox, obj2_rotation)
    
    # 获取Z轴高度
    z_size1 = obj1_bbox.get('z', obj1_bbox.get('height', 0.2))
    z_size2 = obj2_bbox.get('z', obj2_bbox.get('height', 0.2))
    
    # 计算各物体的3D AABB边界
    obj1_x_min = obj1_pos['x'] - x_size1 / 2
    obj1_x_max = obj1_pos['x'] + x_size1 / 2
    obj1_y_min = obj1_pos['y'] - y_size1 / 2
    obj1_y_max = obj1_pos['y'] + y_size1 / 2
    obj1_z_min = obj1_pos['z'] - z_size1 / 2
    obj1_z_max = obj1_pos['z'] + z_size1 / 2
    
    obj2_x_min = obj2_pos['x'] - x_size2 / 2
    obj2_x_max = obj2_pos['x'] + x_size2 / 2
    obj2_y_min = obj2_pos['y'] - y_size2 / 2
    obj2_y_max = obj2_pos['y'] + y_size2 / 2
    obj2_z_min = obj2_pos['z'] - z_size2 / 2
    obj2_z_max = obj2_pos['z'] + z_size2 / 2
    
    # 检查是否在3D空间重叠（使用严格不等式，添加1mm容差，避免边界接触被误判为碰撞）
    tolerance = 0.05  # 1mm容差
    overlap_x = not (obj1_x_max <= obj2_x_min + tolerance or obj1_x_min >= obj2_x_max - tolerance)
    overlap_y = not (obj1_y_max <= obj2_y_min + tolerance or obj1_y_min >= obj2_y_max - tolerance)
    overlap_z = not (obj1_z_max <= obj2_z_min + tolerance or obj1_z_min >= obj2_z_max - tolerance)
    
    if not (overlap_x and overlap_y and overlap_z):
        return 0.0
    
    # 计算重叠区域的尺寸
    overlap_x_min = max(obj1_x_min, obj2_x_min)
    overlap_x_max = min(obj1_x_max, obj2_x_max)
    overlap_y_min = max(obj1_y_min, obj2_y_min)
    overlap_y_max = min(obj1_y_max, obj2_y_max)
    
    # 计算重叠面积
    overlap_width = overlap_x_max - overlap_x_min  # X方向
    overlap_height = overlap_y_max - overlap_y_min  # Y方向
    
    area = overlap_width * overlap_height * 10000  # 转为cm²
    
    return area


def is_within_bounds(obj_pos: Dict, obj_bbox: Dict, obj_rotation: float,
                    bounds: Dict[str, float]) -> Tuple[bool, float, Dict]:
    """
    检查物体是否在边界内
    
    Args:
        obj_pos: 物体中心位置 {'x', 'y', 'z'}
        obj_bbox: 物体包围盒 {'x': short, 'y': long} 或 {'short': ..., 'long': ...}
        obj_rotation: 绕 Z 轴旋转角度（度）
        bounds: 边界 {'x_min', 'x_max', 'y_min', 'y_max'}
    
    Returns:
        (is_within, out_distance, violation_details): 
        - is_within: 是否在边界内
        - out_distance: 最大超出距离（cm，正值表示超出）
        - violation_details: 各方向的详细超出距离 {'west': 0, 'east': 10.5, 'south': 0, 'north': 0}
    """
    # 计算旋转后的实际尺寸 (x_size = X方向占用, y_size = Y方向占用)
    x_size, y_size = rotate_bbox(obj_bbox, obj_rotation)
    
    half_x = x_size / 2   # X 方向半长
    half_y = y_size / 2   # Y 方向半长
    
    # 计算物体的边界
    obj_x_min = obj_pos['x'] - half_x
    obj_x_max = obj_pos['x'] + half_x
    obj_y_min = obj_pos['y'] - half_y
    obj_y_max = obj_pos['y'] + half_y
    
    # 详细记录各方向的超出距离（单位：cm）
    violation_details = {
        'west': max(0, (bounds['x_min'] - obj_x_min) * 100),   # 超出西墙（左边）
        'east': max(0, (obj_x_max - bounds['x_max']) * 100),   # 超出东墙（右边）
        'south': max(0, (bounds['y_min'] - obj_y_min) * 100),  # 超出南墙（前边）
        'north': max(0, (obj_y_max - bounds['y_max']) * 100)   # 超出北墙（后边）
    }
    
    # 计算最大超出距离
    max_violation = max(violation_details.values())
    is_within = max_violation == 0
    
    return is_within, max_violation, violation_details


def calculate_edge_distance(obj_pos: Dict, obj_bbox: Dict, obj_rotation: float,
                           bounds: Dict[str, float]) -> Tuple[float, str]:
    """
    计算物体到最近边缘的距离
    
    Args:
        obj_pos: 物体中心位置
        obj_bbox: 物体包围盒 {'x': short, 'y': long} 或 {'short': ..., 'long': ...}
        obj_rotation: 旋转角度（度）
        bounds: 边界
    
    Returns:
        (min_distance, nearest_edge): 最小距离（cm），最近的边缘名称
    """
    # 计算旋转后的实际尺寸 (x_size = X方向占用, y_size = Y方向占用)
    x_size, y_size = rotate_bbox(obj_bbox, obj_rotation)
    
    half_x = x_size / 2   # X 方向
    half_y = y_size / 2   # Y 方向
    
    # 计算到各个边缘的距离
    distances = {
        'left': (obj_pos['x'] - half_x - bounds['x_min']) * 100,      # X 方向左边
        'right': (bounds['x_max'] - obj_pos['x'] - half_x) * 100,     # X 方向右边
        'front': (obj_pos['y'] - half_y - bounds['y_min']) * 100,     # Y 方向前边
        'back': (bounds['y_max'] - obj_pos['y'] - half_y) * 100       # Y 方向后边
    }
    
    # 找到最小距离
    nearest_edge = min(distances, key=distances.get)
    min_distance = distances[nearest_edge]
    
    return max(0, min_distance), nearest_edge


def calculate_position_ratio(obj_pos: Dict, bounds: Dict[str, float], axis: str = 'y') -> float:
    """
    计算物体在工作表面上的相对位置比例（用于功能分区判断）
    
    Args:
        obj_pos: 物体位置
        bounds: 工作表面边界
        axis: 'y'表示前后方向，'x'表示左右方向
    
    Returns:
        ratio: 0-1之间的比例（0=前/左，1=后/右）
    """
    if axis == 'y':
        min_val = bounds['y_min']
        max_val = bounds['y_max']
        pos_val = obj_pos['y']
    else:  # axis == 'x'
        min_val = bounds['x_min']
        max_val = bounds['x_max']
        pos_val = obj_pos['x']
    
    if max_val == min_val:
        return 0.5
    
    ratio = (pos_val - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, ratio))


def calculate_symmetry_score(objects: List[Dict], center_x: float) -> float:
    """
    计算布局的对称性得分
    
    Args:
        objects: 物体列表
        center_x: 中心线X坐标
    
    Returns:
        symmetry_score: 0-10之间的对称性得分
    """
    if len(objects) == 0:
        return 10.0
    
    # 分组
    left_objects = [obj for obj in objects if obj['position']['x'] < center_x]
    right_objects = [obj for obj in objects if obj['position']['x'] > center_x]
    
    # 数量对称性
    count_symmetry = 1 - abs(len(left_objects) - len(right_objects)) / len(objects)
    
    # 质量对称性（基于物体bbox估算）
    left_mass = sum(obj['bbox']['x'] * obj['bbox']['y'] for obj in left_objects if 'bbox' in obj)
    right_mass = sum(obj['bbox']['x'] * obj['bbox']['y'] for obj in right_objects if 'bbox' in obj)
    total_mass = left_mass + right_mass
    
    if total_mass > 0:
        mass_symmetry = 1 - abs(left_mass - right_mass) / total_mass
    else:
        mass_symmetry = 1.0
    
    # 综合对称性
    symmetry = (count_symmetry + mass_symmetry) / 2
    
    return symmetry * 10


def _normalize_surface_name(name: str) -> str:
    """
    规范化工作表面名称，处理PascalCase和snake_case不一致
    统一返回 snake_case 格式（用于匹配 initial_location）
    
    与 layout_engine_v3.py 中的映射保持一致
    """
    # 建立映射表：PascalCase -> snake_case
    # 统一返回 snake_case 格式，用于匹配 initial_location
    mapping = {
        "ReagentCabinet": "reagent_cabinet",
        "ExperimentalPlatform": "experimental_platform",
        "ValidationPlatform": "validation_platform",
        "FumeHood": "FumeHood",  # 已一致，保持原样
        "fume_hood": "FumeHood",  # snake_case 变体也映射到 FumeHood
        "GloveBox": "GloveBox",  # 已一致，保持原样
        "glove_box": "GloveBox",  # snake_case 变体也映射到 GloveBox
        "RotaryEvaporator": "RotaryEvaporator",  # 已一致，保持原样
        "GravityChromatographyColumn": "GravityChromatographyColumn",  # 已一致，保持原样
    }
    
    # 先尝试直接匹配
    if name in mapping:
        return mapping[name]
    
    # 尝试大小写不敏感匹配
    name_lower = name.lower()
    for key, value in mapping.items():
        if key.lower() == name_lower or value.lower() == name_lower:
            return value
    
    # 如果都不匹配，返回原值
    return name


def get_surface_bounds(layout: Dict, surface_name: str, asset_loader) -> Optional[Dict[str, float]]:
    """
    获取工作表面的边界（公共函数，避免代码重复）
    
    Args:
        layout: 布局JSON
        surface_name: 工作表面的资产ID（如'LabBench', 'FumeHood', 'ValidationPlatform'等）或initial_location（如'experimental_platform'）
        asset_loader: AssetLoader实例，用于获取资产的bbox
    
    Returns:
        bounds: {'x_min', 'x_max', 'y_min', 'y_max'} 或 None（如果未找到）
    """
    # 规范化surface_name
    normalized_surface_name = _normalize_surface_name(surface_name)
    
    # 查找对应的地板物体作为工作表面
    for obj in layout['objects']:
        if obj.get('initial_location') == 'floor':
            asset_id = obj['id']
            
            # 规范化asset_id并匹配
            normalized_asset_id = _normalize_surface_name(asset_id)
            if normalized_asset_id == normalized_surface_name:
                # 获取bbox
                bbox = asset_loader.get_asset_bbox(asset_id)
                pos = obj['position']
                rotation = obj['rotation']['z']
                
                # 根据旋转计算边界
                x_size, y_size = rotate_bbox(bbox, rotation)
                
                half_x = x_size / 2  # X方向半长
                half_y = y_size / 2  # Y方向半长
                
                return {
                    'x_min': pos['x'] - half_x,
                    'x_max': pos['x'] + half_x,
                    'y_min': pos['y'] - half_y,
                    'y_max': pos['y'] + half_y
                }
    
    return None

