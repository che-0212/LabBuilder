"""
根据 LLM 返回的建议修改布局
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 工作台类型列表（移动这些物体时需要同步移动其上的桌面物体）
WORK_SURFACE_TYPES = [
    "ExperimentalPlatform",
    "ValidationPlatform", 
    "FumeHood",
    "LabBench",
    "Workbench",
    "ReagentCabinet",  # 试剂柜，里面有试剂瓶
    "Cabinet",
    "Shelf",  # 架子上也可能有物品
]


class LayoutEditor:
    """应用 LLM 给出的坐标 / 旋转修改"""

    def __init__(self, layout: Dict, asset_loader=None) -> None:
        self.layout = layout
        self.asset_loader = asset_loader
        # 构建同名对象索引映射
        self._build_object_index()
        # 构建工作台到桌面物体的映射
        self._build_surface_to_objects_map()

    def _build_object_index(self) -> None:
        """构建对象索引，用于处理同名对象"""
        self._object_index: Dict[str, List[int]] = {}
        for idx, obj in enumerate(self.layout.get("objects", [])):
            asset_id = obj.get("id", "")
            if asset_id not in self._object_index:
                self._object_index[asset_id] = []
            self._object_index[asset_id].append(idx)

    def _build_surface_to_objects_map(self) -> None:
        """构建工作台到其上物体的映射"""
        self._surface_objects: Dict[str, List[int]] = {}
        for idx, obj in enumerate(self.layout.get("objects", [])):
            initial_location = obj.get("initial_location", "")
            if initial_location and initial_location != "floor":
                if initial_location not in self._surface_objects:
                    self._surface_objects[initial_location] = []
                self._surface_objects[initial_location].append(idx)

    def _normalize_surface_name(self, name: str) -> str:
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

    def _get_surface_front_left_corner(self, surface_obj: Dict) -> Tuple[float, float]:
        """
        计算工作表面的前左角位置
        
        Args:
            surface_obj: 工作表面对象字典，包含 position 和 rotation
        
        Returns:
            (front_left_x, front_left_y): 前左角的全局坐标
        """
        if not self.asset_loader:
            raise ValueError("asset_loader is required for coordinate conversion")
        
        surface_center_x = surface_obj['position']['x']
        surface_center_y = surface_obj['position']['y']
        rotation_z = surface_obj.get('rotation', {}).get('z', 0)
        
        # 获取 bbox
        surface_id = surface_obj['id']
        bbox = self.asset_loader.get_asset_bbox(surface_id)
        
        # 根据旋转计算有效宽度和深度
        # 0°/180°：长边平行于X轴 → width(X方向) = long, depth(Y方向) = short
        # 90°/270°：长边平行于Y轴 → width(X方向) = short, depth(Y方向) = long
        if rotation_z in [90, 270, -90, -270]:
            surface_width = bbox['x']  # short (X方向)
            surface_depth = bbox['y']  # long (Y方向)
        else:
            surface_width = bbox['y']  # long (X方向)
            surface_depth = bbox['x']  # short (Y方向)
        
        # 计算前左角位置
        front_left_x = surface_center_x - surface_width / 2
        front_left_y = surface_center_y - surface_depth / 2
        
        return front_left_x, front_left_y

    def _is_work_surface(self, asset_id: str) -> bool:
        """判断是否是工作台类型"""
        base_id = asset_id.split("#")[0]  # 去掉索引后缀
        return any(ws in base_id for ws in WORK_SURFACE_TYPES)

    def _find_object(self, asset_id: str, index: Optional[int] = None) -> Dict:
        """
        查找对象
        
        Args:
            asset_id: 对象ID
            index: 同名对象的索引（0-based），如果为None则返回第一个
        
        Returns:
            对象字典
        """
        objects = self.layout.get("objects", [])
        
        # 尝试解析带索引的ID格式，如 "Chair#1", "Chair#2"
        if "#" in asset_id:
            parts = asset_id.rsplit("#", 1)
            base_id = parts[0]
            try:
                idx = int(parts[1])
                if base_id in self._object_index and idx < len(self._object_index[base_id]):
                    return objects[self._object_index[base_id][idx]]
            except (ValueError, IndexError):
                pass
        
        # 使用传入的index参数
        if index is not None and asset_id in self._object_index:
            indices = self._object_index[asset_id]
            if index < len(indices):
                return objects[indices[index]]
        
        # 直接匹配
        if asset_id in self._object_index and self._object_index[asset_id]:
            return objects[self._object_index[asset_id][0]]
        
        # 尝试兼容 id 变体（如 Beaker_1）
        for obj in objects:
            if obj.get("id", "").startswith(asset_id + "_"):
                return obj
        
        raise KeyError(f"未找到对象 id={asset_id}")

    def apply_adjustments(self, adjustments: List[Dict]) -> None:
        for item in adjustments:
            # 跳过非dict元素（可能是JSON解析错误导致的）
            if not isinstance(item, dict):
                logger.warning(f"跳过非dict元素: {type(item)} = {item}")
                continue
            
            asset_id = item.get("id")
            if not asset_id:
                continue
            try:
                obj = self._find_object(asset_id)
            except KeyError:
                continue

            # 保存旧的位置和旋转（用于同步桌面物体）
            old_pos = obj.get("position", {}).copy()
            old_rot = obj.get("rotation", {}).get("z", 0)
            
            # 检查是否是工作表面
            is_work_surface = self._is_work_surface(asset_id)
            
            # 处理位置变化
            position = item.get("position")
            position_changed = False
            if position:
                # 计算位移量
                old_x = old_pos.get("x", 0)
                old_y = old_pos.get("y", 0)
                new_x = float(position.get("x", old_x))
                new_y = float(position.get("y", old_y))
                delta_x = new_x - old_x
                delta_y = new_y - old_y
                
                # 更新工作台位置
                obj_pos = obj.setdefault("position", {})
                for axis in ("x", "y", "z"):
                    if axis in position:
                        obj_pos[axis] = float(position[axis])
                        if axis in ("x", "y"):
                            position_changed = True

            # 处理旋转变化
            rotation = item.get("rotation")
            rotation_changed = False
            new_rot = old_rot
            if rotation and "z" in rotation:
                new_rot = float(rotation["z"])
                obj_rot = obj.setdefault("rotation", {})
                obj_rot["z"] = new_rot
                if abs(new_rot - old_rot) > 0.01:  # 容差1度
                    rotation_changed = True
            
            # 处理 initial_location 变化（用于将物体从一个工作表面移动到另一个）
            new_initial_location = item.get("initial_location")
            if new_initial_location:
                old_initial_location = obj.get("initial_location", "")
                # 规范化 initial_location（处理 PascalCase/snake_case 不一致）
                normalized_new_location = self._normalize_surface_name(new_initial_location)
                obj["initial_location"] = normalized_new_location
                
                # 如果 initial_location 发生变化，需要更新内部映射
                if old_initial_location != normalized_new_location:
                    # 从旧的表面映射中移除
                    if old_initial_location in self._surface_objects:
                        obj_idx = self.layout.get("objects", []).index(obj)
                        if obj_idx in self._surface_objects[old_initial_location]:
                            self._surface_objects[old_initial_location].remove(obj_idx)
                    
                    # 添加到新的表面映射中
                    if normalized_new_location != "floor":
                        if normalized_new_location not in self._surface_objects:
                            self._surface_objects[normalized_new_location] = []
                        obj_idx = self.layout.get("objects", []).index(obj)
                        if obj_idx not in self._surface_objects[normalized_new_location]:
                            self._surface_objects[normalized_new_location].append(obj_idx)
                    
                    logger.info(f"Updated initial_location for {asset_id}: {old_initial_location} → {normalized_new_location}")
            
            # 如果是工作表面，同步移动/旋转其上的所有物体
            if is_work_surface:
                new_pos = obj.get("position", {})
                
                # 如果位置或旋转发生变化，需要同步桌面物体
                if position_changed or rotation_changed:
                    # 如果只有位置变化且没有旋转变化，使用简单的平移同步
                    if not rotation_changed and (delta_x != 0 or delta_y != 0):
                        self._sync_desktop_objects(asset_id, delta_x, delta_y)
                    # 如果有旋转变化，使用支持旋转的同步方法
                    elif rotation_changed:
                        self._sync_desktop_objects_with_rotation(
                            asset_id, old_pos, old_rot, new_pos, new_rot
                        )
                    # 如果只有位置变化但旋转也变了（虽然rotation_changed=False，但可能因为容差）
                    elif position_changed:
                        self._sync_desktop_objects(asset_id, delta_x, delta_y)

    def _sync_desktop_objects(self, surface_id: str, delta_x: float, delta_y: float) -> None:
        """同步移动工作台上的所有桌面物体（仅平移）"""
        objects = self.layout.get("objects", [])
        
        # 查找该工作台上的所有物体
        # surface_id可能是 "ExperimentalPlatform" 或 "ExperimentalPlatform#0"
        base_surface_id = surface_id.split("#")[0]
        
        # 规范化工作表面ID
        normalized_surface_id = self._normalize_surface_name(base_surface_id)
        
        for surface_name, obj_indices in self._surface_objects.items():
            # 规范化initial_location名称
            normalized_surface_name = self._normalize_surface_name(surface_name)
            
            # 使用规范化后的值进行精确匹配
            if normalized_surface_id == normalized_surface_name:
                for idx in obj_indices:
                    obj = objects[idx]
                    obj_pos = obj.get("position", {})
                    if "x" in obj_pos:
                        obj_pos["x"] = obj_pos["x"] + delta_x
                    if "y" in obj_pos:
                        obj_pos["y"] = obj_pos["y"] + delta_y

    def _sync_desktop_objects_with_rotation(
        self, 
        surface_id: str, 
        old_pos: Dict, 
        old_rot: float,
        new_pos: Dict, 
        new_rot: float
    ) -> None:
        """
        同步移动和旋转工作台上的所有桌面物体
        
        Args:
            surface_id: 工作表面ID
            old_pos: 旧的位置 {'x': float, 'y': float, 'z': float}
            old_rot: 旧的旋转角度（度）
            new_pos: 新的位置 {'x': float, 'y': float, 'z': float}
            new_rot: 新的旋转角度（度）
        """
        if not self.asset_loader:
            # 如果没有 asset_loader，回退到简单的平移同步
            delta_x = new_pos.get('x', 0) - old_pos.get('x', 0)
            delta_y = new_pos.get('y', 0) - old_pos.get('y', 0)
            self._sync_desktop_objects(surface_id, delta_x, delta_y)
            return
        
        # 1. 获取工作表面对象
        try:
            surface_obj = self._find_object(surface_id)
        except KeyError:
            return
        
        # 2. 计算旧的和新的前左角位置
        old_surface_obj = {
            'id': surface_obj['id'],
            'position': old_pos,
            'rotation': {'z': old_rot}
        }
        new_surface_obj = {
            'id': surface_obj['id'],
            'position': new_pos,
            'rotation': {'z': new_rot}
        }
        
        old_front_left_x, old_front_left_y = self._get_surface_front_left_corner(old_surface_obj)
        new_front_left_x, new_front_left_y = self._get_surface_front_left_corner(new_surface_obj)
        
        # 3. 找到所有桌面物体并更新坐标
        base_surface_id = surface_id.split("#")[0]
        normalized_surface_id = self._normalize_surface_name(base_surface_id)
        
        objects = self.layout.get("objects", [])
        for surface_name, obj_indices in self._surface_objects.items():
            normalized_surface_name = self._normalize_surface_name(surface_name)
            
            if normalized_surface_id == normalized_surface_name:
                for idx in obj_indices:
                    obj = objects[idx]
                    obj_pos = obj.get("position", {})
                    
                    # 转换为局部坐标（相对于旧的工作表面）
                    local_x = obj_pos.get("x", 0) - old_front_left_x
                    local_y = obj_pos.get("y", 0) - old_front_left_y
                    
                    # 转换为新的全局坐标（相对于新的工作表面）
                    obj_pos["x"] = new_front_left_x + local_x
                    obj_pos["y"] = new_front_left_y + local_y
