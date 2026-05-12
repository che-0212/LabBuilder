"""
几何指标计算器
计算布局的几何指标：碰撞、边界违规、高度错误等
"""

import os
import sys
from typing import Dict, List, Tuple, Union
from pathlib import Path

# 添加父目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from labtouchstone.evaluator.utils.geometry import (
    check_bbox_overlap, calculate_overlap_area, 
    is_within_bounds, rotate_bbox
)
from labtouchstone.evaluator.utils.asset_loader import AssetLoader


def _get_rotation_z(rotation: Union[float, Dict]) -> float:
    """
    从rotation字段提取Z轴旋转角度
    
    Args:
        rotation: 可以是float或Dict{'x', 'y', 'z'}
    
    Returns:
        Z轴旋转角度（度）
    """
    if isinstance(rotation, dict):
        return rotation.get('z', 0)
    return rotation if rotation is not None else 0


class GeometryMetrics:
    """几何指标计算器"""
    
    # 墙厚度（与评估器保持一致）
    WALL_THICKNESS = 0.20  # 墙厚20cm
    
    # 工作表面类型（可放置桌面对象的资产）
    WORK_SURFACE_TYPES = [
        'ExperimentalPlatform', 
        'ValidationPlatform', 
        'FumeHood', 
        'GloveBox',
        'ReagentCabinet',
        'RotaryEvaporator',
        'GravityChromatographyColumn'
    ]
    
    # 需要排除的资产（不参与检测）
    EXCLUDED_ASSETS = [
        'LaboratoryRoom'  # 房间本身不应该检测
    ]
    
    # 桌面对象高度容差
    HEIGHT_TOLERANCE = 0.01  # 1cm
    
    # 工作表面的期望高度
    EXPECTED_HEIGHTS = {
        'ExperimentalPlatform': 0.8,
        'ValidationPlatform': 0.8,
        'FumeHood': 0.8,
        'GloveBox': 0.8,
        'ReagentCabinet': 0.0,  # 试剂柜上的物体贴近表面
        'RotaryEvaporator': 0.8,
        'GravityChromatographyColumn': 0.8
    }
    
    def __init__(self, asset_db_path: str):
        """
        初始化指标计算器
        
        Args:
            asset_db_path: assets_annotated.json文件路径
        """
        self.asset_loader = AssetLoader(asset_db_path)
    
    def _calculate_room_bounds(self, layout: Dict) -> Dict[str, float]:
        """
        从布局文件中计算房间边界
        
        Args:
            layout: 布局JSON数据
        
        Returns:
            room_bounds: {'x_min', 'x_max', 'y_min', 'y_max'}
        """
        # 查找房间对象
        room_obj = None
        assets = layout.get('objects', layout.get('layout', []))
        
        for obj in assets:
            asset_id = obj.get('id') or obj.get('asset_id')
            if asset_id == 'LaboratoryRoom':
                room_obj = obj
                break
        
        if not room_obj:
            # 如果没有找到房间对象，使用默认值
            return {
                'x_min': -4.5 + self.WALL_THICKNESS,
                'x_max': 4.5 - self.WALL_THICKNESS,
                'y_min': -4.5 + self.WALL_THICKNESS,
                'y_max': 4.5 - self.WALL_THICKNESS
            }
        
        # 获取房间的bbox和位置
        room_bbox = self.asset_loader.get_asset_bbox('LaboratoryRoom')
        if not room_bbox:
            # 如果找不到bbox，尝试从room_size获取
            room_size = layout.get('room_size', {})
            if room_size:
                room_w = room_size.get('w', 9.0)
                room_d = room_size.get('d', 9.0)
                room_pos = room_obj.get('position', {'x': 0, 'y': 0, 'z': 0})
                room_rot = _get_rotation_z(room_obj.get('rotation', 0))
                
                # 创建临时bbox
                room_bbox = {'short': min(room_w, room_d), 'long': max(room_w, room_d)}
            else:
                # 使用默认值
                room_pos = {'x': 0, 'y': 0, 'z': 0}
                room_rot = 0
                room_bbox = {'short': 9.0, 'long': 9.0}
        else:
            room_pos = room_obj.get('position', {'x': 0, 'y': 0, 'z': 0})
            room_rot = _get_rotation_z(room_obj.get('rotation', 0))
        
        # 根据旋转计算实际尺寸
        x_size, y_size = rotate_bbox(room_bbox, room_rot)
        
        half_x = x_size / 2
        half_y = y_size / 2
        
        # 计算房间边界（扣除墙厚）
        return {
            'x_min': room_pos['x'] - half_x + self.WALL_THICKNESS,
            'x_max': room_pos['x'] + half_x - self.WALL_THICKNESS,
            'y_min': room_pos['y'] - half_y + self.WALL_THICKNESS,
            'y_max': room_pos['y'] + half_y - self.WALL_THICKNESS
        }
    
    def calculate_all(self, layout: Dict, protocol: Dict = None) -> Dict:
        """
        计算所有几何指标
        
        Args:
            layout: 布局JSON数据
            protocol: 协议JSON数据（可选），如果提供，将从protocol读取initial_location
        
        Returns:
            metrics: 包含所有指标的字典
        """
        # 分类资产
        floor_assets = []
        desktop_objects = []
        
        # 支持两种格式：'objects' 或 'layout'
        assets = layout.get('objects', layout.get('layout', []))
        
        for asset in assets:
            # 支持两种字段名：'id' 或 'asset_id'
            asset_id = asset.get('id') or asset.get('asset_id')
            if not asset_id:  # 跳过没有 id 的资产
                continue
            
            # 排除不需要检测的资产
            if asset_id in self.EXCLUDED_ASSETS:
                continue
            
            # 优先从protocol读取initial_location，如果没有则从layout读取
            initial_location = self._get_initial_location(asset_id, protocol, asset.get('initial_location', 'floor'))
            
            if initial_location == 'floor' or asset_id in self.WORK_SURFACE_TYPES:
                floor_assets.append(asset)
            else:
                desktop_objects.append(asset)
        
        # 计算房间边界
        room_bounds = self._calculate_room_bounds(layout)
        
        # 计算各项指标
        collision_details = self._get_collision_details(layout, floor_assets, desktop_objects)
        boundary_details = self._get_boundary_violation_details(layout, floor_assets, desktop_objects, room_bounds, protocol)
        height_details = self._get_height_error_details(layout, desktop_objects, protocol)
        
        return {
            'asset_count': {
                'total': len(assets),
                'floor_assets': len(floor_assets),
                'desktop_objects': len(desktop_objects)
            },
            'collision_count': len(collision_details),
            'boundary_violation_count': len(boundary_details),
            'height_error_count': len(height_details),
            'details': {
                'collisions': collision_details,
                'boundary_violations': boundary_details,
                'height_errors': height_details
            }
        }
    
    def _get_collision_details(self, layout: Dict, floor_assets: List, desktop_objects: List) -> List[Dict]:
        """检测所有碰撞"""
        collisions = []
        
        # 1. 地板资产之间的碰撞
        for i, asset1 in enumerate(floor_assets):
            asset_id1 = asset1.get('id') or asset1.get('asset_id')
            if not asset_id1:
                continue
                
            pos1 = asset1.get('position', {})
            rot1 = _get_rotation_z(asset1.get('rotation', 0))
            
            bbox1 = self.asset_loader.get_asset_bbox(asset_id1)
            if not bbox1:
                continue
            
            for asset2 in floor_assets[i+1:]:
                asset_id2 = asset2.get('id') or asset2.get('asset_id')
                if not asset_id2:
                    continue
                    
                pos2 = asset2.get('position', {})
                rot2 = _get_rotation_z(asset2.get('rotation', 0))
                
                bbox2 = self.asset_loader.get_asset_bbox(asset_id2)
                if not bbox2:
                    continue
                
                # 检查 Z 轴高度，排除"在表面上"的合理布局
                z_diff = pos1.get('z', 0) - pos2.get('z', 0)
                
                # 情况1: asset1 在 asset2 上方（至少1cm）
                if z_diff > 0.01:
                    # 检查 asset1 是否在 asset2 的 XY 范围内
                    x_size2, y_size2 = rotate_bbox(bbox2, rot2)
                    asset2_x_min = pos2['x'] - x_size2 / 2
                    asset2_x_max = pos2['x'] + x_size2 / 2
                    asset2_y_min = pos2['y'] - y_size2 / 2
                    asset2_y_max = pos2['y'] + y_size2 / 2
                    
                    x_size1, y_size1 = rotate_bbox(bbox1, rot1)
                    asset1_x_min = pos1['x'] - x_size1 / 2
                    asset1_x_max = pos1['x'] + x_size1 / 2
                    asset1_y_min = pos1['y'] - y_size1 / 2
                    asset1_y_max = pos1['y'] + y_size1 / 2
                    
                    tolerance = 0.05  # 5cm容差
                    if (asset1_x_min >= asset2_x_min - tolerance and 
                        asset1_x_max <= asset2_x_max + tolerance and
                        asset1_y_min >= asset2_y_min - tolerance and 
                        asset1_y_max <= asset2_y_max + tolerance):
                        # asset1 在 asset2 表面上，跳过碰撞检测
                        continue
                
                # 情况2: asset2 在 asset1 上方（至少1cm）
                elif z_diff < -0.01:
                    # 检查 asset2 是否在 asset1 的 XY 范围内
                    x_size1, y_size1 = rotate_bbox(bbox1, rot1)
                    asset1_x_min = pos1['x'] - x_size1 / 2
                    asset1_x_max = pos1['x'] + x_size1 / 2
                    asset1_y_min = pos1['y'] - y_size1 / 2
                    asset1_y_max = pos1['y'] + y_size1 / 2
                    
                    x_size2, y_size2 = rotate_bbox(bbox2, rot2)
                    asset2_x_min = pos2['x'] - x_size2 / 2
                    asset2_x_max = pos2['x'] + x_size2 / 2
                    asset2_y_min = pos2['y'] - y_size2 / 2
                    asset2_y_max = pos2['y'] + y_size2 / 2
                    
                    tolerance = 0.05  # 5cm容差
                    if (asset2_x_min >= asset1_x_min - tolerance and 
                        asset2_x_max <= asset1_x_max + tolerance and
                        asset2_y_min >= asset1_y_min - tolerance and 
                        asset2_y_max <= asset1_y_max + tolerance):
                        # asset2 在 asset1 表面上，跳过碰撞检测
                        continue
                
                is_overlap, _ = check_bbox_overlap(pos1, bbox1, rot1, pos2, bbox2, rot2)
                
                if is_overlap:
                    overlap_area = calculate_overlap_area(pos1, bbox1, rot1, pos2, bbox2, rot2)
                    
                    if overlap_area >= 1.0:  # 忽略小于1cm²的重叠
                        collisions.append({
                            'object1': asset_id1,
                            'object2': asset_id2,
                            'work_surface': 'floor',
                            'overlap_area_cm2': overlap_area
                        })
        
        # 2. 按工作表面分组的桌面对象碰撞
        desktop_by_surface = {}
        for obj in desktop_objects:
            surface = obj.get('initial_location', 'unknown')
            if surface not in desktop_by_surface:
                desktop_by_surface[surface] = []
            desktop_by_surface[surface].append(obj)
        
        for surface, objects in desktop_by_surface.items():
            for i, obj1 in enumerate(objects):
                obj_id1 = obj1.get('id') or obj1.get('asset_id')
                if not obj_id1:
                    continue
                    
                pos1 = obj1.get('position', {})
                rot1 = _get_rotation_z(obj1.get('rotation', 0))
                
                bbox1 = self.asset_loader.get_asset_bbox(obj_id1)
                if not bbox1:
                    continue
                
                for obj2 in objects[i+1:]:
                    obj_id2 = obj2.get('id') or obj2.get('asset_id')
                    if not obj_id2:
                        continue
                        
                    pos2 = obj2.get('position', {})
                    rot2 = _get_rotation_z(obj2.get('rotation', 0))
                    
                    bbox2 = self.asset_loader.get_asset_bbox(obj_id2)
                    if not bbox2:
                        continue
                    
                    is_overlap, _ = check_bbox_overlap(pos1, bbox1, rot1, pos2, bbox2, rot2)
                    
                    if is_overlap:
                        overlap_area = calculate_overlap_area(pos1, bbox1, rot1, pos2, bbox2, rot2)
                        
                        if overlap_area >= 2.0:  # 桌面对象容差2cm²
                            collisions.append({
                                'object1': obj_id1,
                                'object2': obj_id2,
                                'work_surface': surface,
                                'overlap_area_cm2': overlap_area
                            })
        
        return collisions
    
    def _get_boundary_violation_details(self, layout: Dict, floor_assets: List, desktop_objects: List, room_bounds: Dict, protocol: Dict = None) -> List[Dict]:
        """检测所有边界违规"""
        violations = []
        
        # 1. 地板资产的房间边界检查
        for asset in floor_assets:
            asset_id = asset.get('id') or asset.get('asset_id')
            if not asset_id:
                continue
                
            pos = asset.get('position', {})
            rot = _get_rotation_z(asset.get('rotation', 0))
            
            bbox = self.asset_loader.get_asset_bbox(asset_id)
            if not bbox:
                continue
            
            is_within, out_distance, _ = is_within_bounds(pos, bbox, rot, room_bounds)
            
            if not is_within and out_distance > 0.5:  # 容差0.5cm
                violations.append({
                    'object': asset_id,
                    'work_surface': 'floor',
                    'out_distance_cm': out_distance
                })
        
        # 2. 桌面对象的工作表面边界检查
        for obj in desktop_objects:
            obj_id = obj.get('id') or obj.get('asset_id')
            if not obj_id:
                continue
            
            # 优先从protocol读取initial_location
            surface_id = self._get_initial_location(obj_id, protocol, obj.get('initial_location'))
            
            if not surface_id:
                continue
            
            # 规范化表面名称（处理PascalCase和snake_case不一致）
            normalized_surface_id = self._normalize_surface_name(surface_id)
            
            # 查找工作表面
            surface_asset = None
            for asset in floor_assets:
                asset_id = asset.get('id') or asset.get('asset_id')
                # 尝试精确匹配和规范化匹配
                if asset_id == surface_id or asset_id == normalized_surface_id:
                    surface_asset = asset
                    break
                # 也尝试规范化asset_id后比较
                normalized_asset_id = self._normalize_surface_name(asset_id)
                if normalized_asset_id == normalized_surface_id:
                    surface_asset = asset
                    break
            
            if not surface_asset:
                continue
            
            surface_pos = surface_asset.get('position', {})
            surface_rot = _get_rotation_z(surface_asset.get('rotation', 0))
            surface_bbox = self.asset_loader.get_asset_bbox(surface_id)
            
            if not surface_bbox:
                continue
            
            # 计算工作表面边界（添加边缘容差，物体不应该完全贴边）
            x_size, y_size = rotate_bbox(surface_bbox, surface_rot)
            edge_margin = 0.00# 5cm边缘容差
            surface_bounds = {
                'x_min': surface_pos['x'] - x_size / 2 + edge_margin,
                'x_max': surface_pos['x'] + x_size / 2 - edge_margin,
                'y_min': surface_pos['y'] - y_size / 2 + edge_margin,
                'y_max': surface_pos['y'] + y_size / 2 - edge_margin
            }
            
            # 检查桌面对象是否在表面边界内
            obj_pos = obj.get('position', {})
            obj_rot = _get_rotation_z(obj.get('rotation', 0))
            obj_bbox = self.asset_loader.get_asset_bbox(obj_id)
            
            if not obj_bbox:
                continue
            
            is_within, out_distance, _ = is_within_bounds(obj_pos, obj_bbox, obj_rot, surface_bounds)
            
            if not is_within and out_distance > 1.0:  # 容差1cm
                violations.append({
                    'object': obj_id,
                    'work_surface': surface_id,
                    'out_distance_cm': out_distance
                })
        
        return violations
    
    def _get_reagent_layer_height(self, asset_id: str) -> float:
        """
        根据试剂的化学属性确定其在ReagentCabinet中的分层高度
        
        Args:
            asset_id: 试剂资产ID
        
        Returns:
            期望的Z轴高度（米）
        """
        asset_info = self.asset_loader.get_asset_info(asset_id)
        if not asset_info:
            return 1.5  # 默认：一般试剂层
        
        props = asset_info.get('props', {})
        
        # 分层规则（优先级：acid > base > flammable/oxidizer/reactive_metal > 其他）
        if props.get('acid'):
            return 0.8  # Layer 1: 酸类（底层）
        elif props.get('base'):
            return 1.1  # Layer 2: 碱类（中下层）
        elif props.get('flammable') or props.get('oxidizer') or props.get('reactive_metal'):
            return 1.3  # Layer 3: 易燃/氧化剂/活泼金属（中上层）
        else:
            return 1.5  # Layer 4: 一般试剂（顶层）
    
    def _get_height_error_details(self, layout: Dict, desktop_objects: List, protocol: Dict = None) -> List[Dict]:
        """检测所有高度错误"""
        errors = []
        
        for obj in desktop_objects:
            obj_id = obj.get('id') or obj.get('asset_id')
            if not obj_id:
                continue
            
            # 优先从protocol读取initial_location
            surface_id = self._get_initial_location(obj_id, protocol, obj.get('initial_location'))
            obj_pos = obj.get('position', {})
            
            if not surface_id:
                continue
            
            # 特殊处理：ReagentCabinet中的试剂使用分层高度
            if surface_id == 'ReagentCabinet' or surface_id == 'reagent_cabinet':
                # 根据化学属性确定期望高度
                expected_z = self._get_reagent_layer_height(obj_id)
            elif surface_id in self.EXPECTED_HEIGHTS:
                expected_z = self.EXPECTED_HEIGHTS[surface_id]
            else:
                continue  # 未知的工作表面，跳过
            
            actual_z = obj_pos.get('z', 0)
            error = abs(actual_z - expected_z)
            
            if error > self.HEIGHT_TOLERANCE:
                errors.append({
                    'object': obj_id,
                    'work_surface': surface_id,
                    'expected_height_m': expected_z,
                    'actual_height_m': actual_z,
                    'error_m': error,
                    'error_cm': error * 100
                })
        
        return errors
    
    def _normalize_surface_name(self, name: str) -> str:
        """
        规范化表面名称（处理PascalCase和snake_case不一致）
        
        Args:
            name: 表面名称（可能是"ReagentCabinet"或"reagent_cabinet"）
        
        Returns:
            规范化后的名称（统一为snake_case）
        """
        if not name:
            return name
        
        # 将PascalCase转换为snake_case
        import re
        # 在单词边界插入下划线，然后转小写
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        normalized = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        # 处理常见的不一致
        name_mapping = {
            'reagentcabinet': 'reagent_cabinet',
            'fumehood': 'fume_hood',
            'experimentalplatform': 'experimental_platform',
            'validationplatform': 'validation_platform',
            'glovebox': 'glove_box',
            'rotaryevaporator': 'rotary_evaporator',
        }
        
        return name_mapping.get(normalized, normalized)
    
    def _get_initial_location(self, asset_id: str, protocol: Dict = None, default: str = 'floor') -> str:
        """
        从protocol或layout中获取资产的initial_location
        
        Args:
            asset_id: 资产ID
            protocol: 协议JSON数据（可选）
            default: 默认值（如果都找不到）
        
        Returns:
            initial_location字符串
        """
        # 优先从protocol读取
        if protocol:
            assets = protocol.get('assets', [])
            for asset in assets:
                if asset.get('id') == asset_id:
                    initial_location = asset.get('initial_location')
                    if initial_location:
                        return initial_location
        
        # 如果protocol中没有，返回默认值
        return default

