"""
物理约束检查器
检查边界、碰撞、高度等物理约束
"""

from typing import Dict, List, Tuple
from labtouchstone.evaluator.utils.geometry import (
    is_within_bounds, check_bbox_overlap, calculate_overlap_area
)
from labtouchstone.evaluator.utils.asset_loader import AssetLoader
from labtouchstone.evaluator.config import PHYSICAL_CONSTRAINTS


class PhysicalConstraintChecker:
    """物理约束检查器"""
    
    def __init__(self, asset_loader: AssetLoader):
        """
        初始化物理约束检查器
        
        Args:
            asset_loader: 资产加载器实例
        """
        self.asset_loader = asset_loader
        self.config = PHYSICAL_CONSTRAINTS
    
    def check_all(self, layout: Dict, protocol: Dict = None) -> Dict:
        """
        检查所有物理约束
        
        Args:
            layout: 布局JSON数据
            protocol: 协议JSON数据（用于获取资产的应有位置）
        
        Returns:
            result: 包含得分和违规信息的字典
        """
        result = {
            'score': 35,  # 12+12+5+6=35
            'max_score': 35,
            'location_mismatch': {},  # 新增：location-position不匹配检测
            'boundary': {},
            'collision': {},
            'height': {},
            'room_assets': {},
            'violations': []
        }
        
        # 0. Location-Position匹配检查（最高优先级，CRITICAL）
        location_result = self.check_location_position_match(layout)
        result['location_mismatch'] = location_result
        result['violations'].extend(location_result['violations'])
        
        # 1. 边界检查（非地板物体）
        boundary_result = self.check_boundaries(layout, protocol)
        result['boundary'] = boundary_result
        result['score'] -= boundary_result['deduction']
        result['violations'].extend(boundary_result['violations'])
        
        # 2. 碰撞检查（非地板物体）
        collision_result = self.check_collisions(layout)
        result['collision'] = collision_result
        result['score'] -= collision_result['deduction']
        result['violations'].extend(collision_result['violations'])
        
        # 3. 高度检查（非地板物体）
        height_result = self.check_heights(layout)
        result['height'] = height_result
        result['score'] -= height_result['deduction']
        result['violations'].extend(height_result['violations'])
        
        # 4. 地板物体检查
        room_result = self.check_room_assets(layout)
        result['room_assets'] = room_result
        result['score'] -= room_result['deduction']
        result['violations'].extend(room_result['violations'])
        
        result['score'] = max(0, result['score'])
        
        return result
    
    def check_boundaries(self, layout: Dict, protocol: Dict = None) -> Dict:
        """
        检查边界约束
        
        从protocol读取资产的应有位置(initial_location)，检查资产是否在那个surface的bbox内
        
        Args:
            layout: 布局JSON
            protocol: 协议JSON（包含资产的应有位置信息）
        
        Returns:
            result: 边界检查结果
        """
        max_score = self.config['boundary']['max_score']
        deduction_rules = self.config['boundary']['deduction_rules']
        violations = []
        total_deduction = 0
        
        # 获取所有非地板物体（initial_location != 'floor'）
        desktop_objects = [obj for obj in layout['objects'] if obj.get('initial_location') != 'floor']
        
        # 从protocol构建资产位置映射
        expected_locations = {}
        if protocol and 'assets' in protocol:
            for asset in protocol['assets']:
                asset_name = asset.get('name')
                initial_loc = asset.get('initial_location')
                if asset_name and initial_loc:
                    expected_locations[asset_name] = initial_loc
        
        for obj in desktop_objects:
            asset_id = obj['id']
            pos = obj['position']
            
            # 从protocol获取资产的应有位置，如果没有则使用layout的initial_location作为fallback
            expected_location = expected_locations.get(asset_id)
            if not expected_location:
                # 使用layout中的initial_location作为fallback
                expected_location = obj.get('initial_location')
            
            if not expected_location or expected_location == 'floor':
                # 没有位置信息或应该在地板上，跳过
                continue
            
            # 获取应有位置的边界
            bounds = self._get_surface_bounds(layout, expected_location)
            
            if bounds is None:
                continue
            
            # 获取物体信息
            bbox = self.asset_loader.get_asset_bbox(asset_id)
            rotation = obj['rotation']['z']
            
            # 检查是否在边界内
            is_within, out_distance, violation_details = is_within_bounds(pos, bbox, rotation, bounds)
            
            if not is_within:
                # 根据超出距离确定扣分
                deduction = self._get_deduction(out_distance, deduction_rules)
                total_deduction += deduction
                
                violations.append({
                    'constraint': 'boundary_check',
                    'severity': 'high',
                    'object': asset_id,
                    'work_surface': expected_location,
                    'expected': f"should be in {expected_location} bounds [{bounds['x_min']:.2f}, {bounds['x_max']:.2f}] × [{bounds['y_min']:.2f}, {bounds['y_max']:.2f}]",
                    'actual': f"position ({pos['x']:.2f}, {pos['y']:.2f}) is {out_distance:.1f}cm outside {expected_location}",
                    'out_of_bounds_distance': out_distance,
                    'violation_details': violation_details,
                    'current_position': pos.copy(),
                    'current_rotation': rotation,
                    'deduction': deduction
                })
        
        final_deduction = min(max_score, total_deduction)
        
        return {
            'score': max(0, max_score - final_deduction),
            'max_score': max_score,
            'violations': violations,
            'deduction': final_deduction,
            'passed': len(violations) == 0
        }
    
    def check_collisions(self, layout: Dict) -> Dict:
        """
        检查碰撞约束
        
        Args:
            layout: 布局JSON
        
        Returns:
            result: 碰撞检查结果
        """
        max_score = self.config['collision']['max_score']
        deduction_rules = self.config['collision']['deduction_rules']
        violations = []
        total_deduction = 0
        
        # 获取所有非地板物体并按工作表面分组
        desktop_objects = [obj for obj in layout['objects'] if obj.get('initial_location') != 'floor']
        
        # 按工作表面分组
        surface_groups = {}
        for obj in desktop_objects:
            surface = obj['initial_location']
            if surface not in surface_groups:
                surface_groups[surface] = []
            surface_groups[surface].append(obj)
        
        # 对每个工作表面，检查物体两两碰撞
        for surface, objects in surface_groups.items():
            for i, obj1 in enumerate(objects):
                for obj2 in objects[i+1:]:
                    # 获取物体信息
                    asset_id1 = obj1['id']
                    asset_id2 = obj2['id']
                    bbox1 = self.asset_loader.get_asset_bbox(asset_id1)
                    bbox2 = self.asset_loader.get_asset_bbox(asset_id2)
                    pos1 = obj1['position']
                    pos2 = obj2['position']
                    rot1 = obj1['rotation']['z']
                    rot2 = obj2['rotation']['z']
                    
                    # 检查碰撞
                    is_overlap, overlap_dist = check_bbox_overlap(pos1, bbox1, rot1, pos2, bbox2, rot2)
                    
                    if is_overlap:
                        # 计算重叠面积
                        overlap_area = calculate_overlap_area(pos1, bbox1, rot1, pos2, bbox2, rot2)
                        
                        # 根据重叠面积确定扣分
                        deduction = self._get_deduction(overlap_area, deduction_rules)
                        total_deduction += deduction
                        
                        violations.append({
                            'constraint': 'collision_check',
                            'severity': 'high',
                            'objects': [asset_id1, asset_id2],
                            'work_surface': surface,
                            'expected': "物体之间不重叠，最小间距≥2cm",
                            'actual': f"物体发生碰撞，重叠面积约{overlap_area:.1f}cm²",
                            'overlap_area': overlap_area,
                            'overlap_distance': overlap_dist,
                            'positions': {  # ← 新增：记录两个物体的位置
                                asset_id1: pos1.copy(),
                                asset_id2: pos2.copy()
                            },
                            'bboxes': {  # ← 新增：记录两个物体的bbox
                                asset_id1: bbox1,
                                asset_id2: bbox2
                            },
                            'rotations': {  # ← 新增：记录两个物体的旋转
                                asset_id1: rot1,
                                asset_id2: rot2
                            },
                            'deduction': deduction
                        })
        
        final_deduction = min(max_score, total_deduction)
        
        return {
            'score': max(0, max_score - final_deduction),
            'max_score': max_score,
            'violations': violations,
            'deduction': final_deduction,
            'passed': len(violations) == 0
        }
    
    def check_heights(self, layout: Dict) -> Dict:
        """
        检查高度约束
        
        检查所有物体（包括房间资产和桌面物体）是否在正确的高度上：
        - 房间资产（initial_location == 'floor'）：应该在地面，z = 0.0m
        - 桌面物体（initial_location != 'floor'）：应该在对应工作表面的高度上
          工作表面的高度从资产库动态获取
        
        Args:
            layout: 布局JSON
        
        Returns:
            result: 高度检查结果
        """
        max_score = self.config['height']['max_score']
        expected_heights = self.config['height']['expected_heights']
        tolerance = self.config['height']['tolerance']
        deduction_rules = self.config['height']['deduction_rules']
        violations = []
        total_deduction = 0
        
        # 检查所有物体（包括房间资产和桌面物体）
        for obj in layout['objects']:
            initial_location = obj.get('initial_location')
            if initial_location is None:
                continue
            
            # 根据 initial_location 确定期望高度
            if initial_location == 'floor':
                # 房间资产应该在地面
                expected_z = expected_heights.get('floor', 0.0)
                actual_z = obj['position']['z']
                error = abs(actual_z - expected_z)
            elif 'ReagentCabinet' in initial_location or 'reagent_cabinet' in initial_location:
                # 试剂柜支持多层存储：0.8m, 1.1m, 1.3m, 1.5m
                # 允许0.75-1.55m范围内的高度（±0.05m容差）
                actual_z = obj['position']['z']
                if 0.75 <= actual_z <= 1.55:
                    # 高度在合法范围内，无需检查
                    continue
                else:
                    # 超出范围，计算与最近合法高度的误差
                    if actual_z < 0.75:
                        expected_z = 0.8
                        error = abs(actual_z - expected_z)
                    else:  # actual_z > 1.55
                        expected_z = 1.5
                        error = abs(actual_z - expected_z)
            else:
                # 其他桌面物体应该在对应工作表面的高度上
                # 所有work surface的台面高度统一为0.8m
                expected_z = 0.8
                actual_z = obj['position']['z']
                error = abs(actual_z - expected_z)
            
            if error > tolerance:
                # 根据误差确定扣分
                deduction = self._get_deduction(error, deduction_rules)
                total_deduction += deduction
                
                violations.append({
                    'constraint': 'height_check',
                    'severity': 'hard',
                    'object': obj['id'],
                    'initial_location': initial_location,
                    'expected': f"z = {expected_z}m",
                    'actual': f"z = {actual_z}m",
                    'error': error,
                    'deduction': deduction
                })
        
        final_deduction = min(max_score, total_deduction)
        
        return {
            'score': max(0, max_score - final_deduction),
            'max_score': max_score,
            'violations': violations,
            'deduction': final_deduction,
            'passed': len(violations) == 0
        }
    
    def check_room_assets(self, layout: Dict) -> Dict:
        """
        检查地板物体的物理约束（边界和碰撞）
        
        Args:
            layout: 布局JSON
        
        Returns:
            result: 地板物体检查结果
        """
        violations = []
        total_deduction = 0
        max_score = 6  # 分配6分给地板物体检查
        
        # 获取所有地板物体（initial_location == 'floor'）
        room_assets = [obj for obj in layout['objects'] if obj.get('initial_location') == 'floor']
        
        if len(room_assets) == 0:
            return {
                'score': max_score,
                'max_score': max_score,
                'violations': [],
                'deduction': 0,
                'passed': True
            }
        
        # 找到房间资产（LaboratoryRoom），用它的边界作为房间边界
        room_obj = None
        for obj in room_assets:
            if 'Room' in obj['id'] or 'room' in obj['id'].lower():
                room_obj = obj
                break
        
        # 如果没有找到房间，跳过房间边界检查
        if room_obj is None:
            return {
                'score': max_score,
                'max_score': max_score,
                'violations': [],
                'deduction': 0,
                'passed': True
            }
        
        # 根据房间的位置和bbox计算房间边界
        room_bbox = self.asset_loader.get_asset_bbox(room_obj['id'])
        room_pos = room_obj['position']
        room_rot = room_obj['rotation']['z']
        
        # 根据旋转计算实际尺寸
        from labtouchstone.evaluator.utils.geometry import rotate_bbox
        actual_depth, actual_width = rotate_bbox(room_bbox, room_rot)
        # rotate_bbox返回 (depth, width)，其中depth是X方向，width是Y方向
        
        half_depth = actual_depth / 2  # X方向半长
        half_width = actual_width / 2   # Y方向半长
        
        # 墙厚度 = 0.20m，需要从外墙边界减去墙厚度得到内墙边界
        WALL_THICKNESS = 0.20
        
        ROOM_BOUNDS = {
            'x_min': room_pos['x'] - half_depth + WALL_THICKNESS,  # 内墙左边界
            'x_max': room_pos['x'] + half_depth - WALL_THICKNESS,  # 内墙右边界
            'y_min': room_pos['y'] - half_width + WALL_THICKNESS,  # 内墙前边界
            'y_max': room_pos['y'] + half_width - WALL_THICKNESS   # 内墙后边界
        }
        
        # 内部可用空间尺寸
        interior_width = actual_depth - 2 * WALL_THICKNESS  # X方向
        interior_depth = actual_width - 2 * WALL_THICKNESS  # Y方向
        room_size_str = f"{interior_width:.2f}m × {interior_depth:.2f}m (interior usable space)"
        
        # 1. 检查其他地板物体是否超出房间边界（不检查房间自己）
        for obj in room_assets:
            asset_id = obj['id']
            
            # 跳过房间本身
            if 'Room' in asset_id or 'room' in asset_id.lower():
                continue
            
            bbox = self.asset_loader.get_asset_bbox(asset_id)
            pos = obj['position']
            rotation = obj['rotation']['z']
            
            is_within, out_distance, violation_details = is_within_bounds(pos, bbox, rotation, ROOM_BOUNDS)
            
            # 添加浮点数容差判断，避免极小误差造成误报
            if not is_within and out_distance > 0.001:  # 容差0.1mm
                deduction = min(3.0, out_distance / 100)  # 超出房间边界最多扣3分
                total_deduction += deduction
                
                violations.append({
                    'constraint': 'room_boundary_check',
                    'severity': 'high',
                    'object': asset_id,
                    'expected': f"在房间范围内 ({room_size_str})",
                    'actual': f"超出房间边界 {out_distance:.1f}cm",
                    'out_of_bounds_distance': out_distance,
                    'violation_details': violation_details,  # ← 新增：详细方向信息
                    'current_position': pos.copy(),  # ← 新增：当前位置
                    'current_rotation': rotation,  # ← 新增：当前旋转
                    'deduction': deduction
                })
        
        # 2. 检查地板物体之间的碰撞（不包括房间本身）
        non_room_assets = [obj for obj in room_assets 
                          if 'Room' not in obj['id'] and 'room' not in obj['id'].lower()]
        
        for i, obj1 in enumerate(non_room_assets):
            for obj2 in non_room_assets[i+1:]:
                asset_id1 = obj1['id']
                asset_id2 = obj2['id']
                bbox1 = self.asset_loader.get_asset_bbox(asset_id1)
                bbox2 = self.asset_loader.get_asset_bbox(asset_id2)
                pos1 = obj1['position']
                pos2 = obj2['position']
                rot1 = obj1['rotation']['z']
                rot2 = obj2['rotation']['z']
                
                # 检查是否是"在表面上"的合理布局（改进版）
                # 检查一个物体是否完全在另一个物体的表面上（如computer在desk上）
                z_diff = pos1['z'] - pos2['z']
                
                # 情况1: obj1在obj2上方
                if z_diff > 0.01:  # obj1的z高于obj2至少1cm
                    # 计算obj2旋转后的xy边界
                    from .utils.geometry import rotate_bbox
                    width2, depth2 = rotate_bbox(bbox2, rot2)
                    obj2_x_min = pos2['x'] - width2 / 2
                    obj2_x_max = pos2['x'] + width2 / 2
                    obj2_y_min = pos2['y'] - depth2 / 2
                    obj2_y_max = pos2['y'] + depth2 / 2
                    
                    # 计算obj1旋转后的xy边界
                    width1, depth1 = rotate_bbox(bbox1, rot1)
                    obj1_x_min = pos1['x'] - width1 / 2
                    obj1_x_max = pos1['x'] + width1 / 2
                    obj1_y_min = pos1['y'] - depth1 / 2
                    obj1_y_max = pos1['y'] + depth1 / 2
                    
                    # 检查obj1是否完全在obj2的xy范围内（允许5cm误差）
                    tolerance = 0.05  # 5cm容差
                    if (obj1_x_min >= obj2_x_min - tolerance and 
                        obj1_x_max <= obj2_x_max + tolerance and
                        obj1_y_min >= obj2_y_min - tolerance and 
                        obj1_y_max <= obj2_y_max + tolerance):
                        # obj1在obj2表面上，跳过碰撞检测
                        continue
                
                # 情况2: obj2在obj1上方
                elif z_diff < -0.01:  # obj2的z高于obj1至少1cm
                    from .utils.geometry import rotate_bbox
                    width1, depth1 = rotate_bbox(bbox1, rot1)
                    obj1_x_min = pos1['x'] - width1 / 2
                    obj1_x_max = pos1['x'] + width1 / 2
                    obj1_y_min = pos1['y'] - depth1 / 2
                    obj1_y_max = pos1['y'] + depth1 / 2
                    
                    width2, depth2 = rotate_bbox(bbox2, rot2)
                    obj2_x_min = pos2['x'] - width2 / 2
                    obj2_x_max = pos2['x'] + width2 / 2
                    obj2_y_min = pos2['y'] - depth2 / 2
                    obj2_y_max = pos2['y'] + depth2 / 2
                    
                    tolerance = 0.05
                    if (obj2_x_min >= obj1_x_min - tolerance and 
                        obj2_x_max <= obj1_x_max + tolerance and
                        obj2_y_min >= obj1_y_min - tolerance and 
                        obj2_y_max <= obj1_y_max + tolerance):
                        # obj2在obj1表面上，跳过碰撞检测
                        continue
                
                is_overlap, overlap_dist = check_bbox_overlap(pos1, bbox1, rot1, pos2, bbox2, rot2)
                
                if is_overlap:
                    overlap_area = calculate_overlap_area(pos1, bbox1, rot1, pos2, bbox2, rot2)
                    
                    # 如果重叠面积很小（可能是浮点误差），跳过
                    if overlap_area < 1.0:  # 小于1cm²
                        continue
                    
                    deduction = min(3.0, overlap_area / 1000)  # 地板物体碰撞最多扣3分
                    total_deduction += deduction
                    
                    violations.append({
                        'constraint': 'room_collision_check',
                        'severity': 'high',
                        'objects': [asset_id1, asset_id2],
                        'expected': "地板物体之间不重叠",
                        'actual': f"发生碰撞，重叠面积约{overlap_area:.1f}cm²",
                        'overlap_area': overlap_area,
                        'positions': {  # ← 新增：记录两个物体的位置
                            asset_id1: pos1.copy(),
                            asset_id2: pos2.copy()
                        },
                        'bboxes': {  # ← 新增：记录两个物体的bbox
                            asset_id1: bbox1,
                            asset_id2: bbox2
                        },
                        'rotations': {  # ← 新增：记录两个物体的旋转
                            asset_id1: rot1,
                            asset_id2: rot2
                        },
                        'deduction': deduction
                    })
        
        final_deduction = min(max_score, total_deduction)
        
        return {
            'score': max(0, max_score - final_deduction),
            'max_score': max_score,
            'violations': violations,
            'deduction': final_deduction,
            'passed': len(violations) == 0
        }
    
    def _get_surface_bounds(self, layout: Dict, surface_name: str) -> Dict[str, float]:
        """
        获取工作表面的边界
        
        Args:
            layout: 布局JSON
            surface_name: 工作表面的资产ID（如'LabBench', 'FumeHood', 'ValidationPlatform'等）
        
        Returns:
            bounds: {'x_min', 'x_max', 'y_min', 'y_max'}
        """
        # 使用公共函数避免代码重复
        from labtouchstone.evaluator.utils.geometry import get_surface_bounds
        return get_surface_bounds(layout, surface_name, self.asset_loader)
    
    def check_location_position_match(self, layout: Dict) -> Dict:
        """
        检查桌面物体的location标记与实际position是否匹配（CRITICAL优先级）
        
        这是最高优先级的检查，因为如果location标记错误，
        其他所有检查（边界、碰撞）都会基于错误的surface进行判断。
        
        Args:
            layout: 布局JSON
        
        Returns:
            result: 不匹配检测结果
        """
        mismatches = []
        
        # 获取所有桌面物体
        desktop_objects = [obj for obj in layout['objects'] if obj.get('initial_location') != 'floor']
        
        for obj in desktop_objects:
            marked_location = obj.get('initial_location')
            obj_id = obj['id']
            obj_pos = obj['position']
            
            # 获取标记的surface边界
            marked_bounds = self._get_surface_bounds(layout, marked_location)
            
            if marked_bounds is None:
                # surface不存在
                mismatches.append({
                    'constraint': 'location_mismatch',
                    'severity': 'critical',
                    'object': obj_id,
                    'issue_type': 'surface_not_found',
                    'marked_location': marked_location,
                    'actual_position': obj_pos,
                    'expected': f'{obj_id} is marked as {marked_location}',
                    'actual': f'Work surface {marked_location} not found in layout',
                    'suggestion': f'Please verify if {marked_location} exists in the layout, or reassign {obj_id} to another surface'
                })
                continue
            
            # 检查坐标是否在标记的surface边界内（只检查中心点，不考虑bbox）
            pos_in_x = marked_bounds['x_min'] <= obj_pos['x'] <= marked_bounds['x_max']
            pos_in_y = marked_bounds['y_min'] <= obj_pos['y'] <= marked_bounds['y_max']
            
            if not (pos_in_x and pos_in_y):
                # 位置不匹配，尝试找到实际所在的surface
                actual_surface = self._find_surface_containing_position(layout, obj_pos)
                
                # 计算偏离距离
                dist_x = 0
                dist_y = 0
                if not pos_in_x:
                    if obj_pos['x'] < marked_bounds['x_min']:
                        dist_x = (marked_bounds['x_min'] - obj_pos['x']) * 100
                    else:
                        dist_x = (obj_pos['x'] - marked_bounds['x_max']) * 100
                if not pos_in_y:
                    if obj_pos['y'] < marked_bounds['y_min']:
                        dist_y = (marked_bounds['y_min'] - obj_pos['y']) * 100
                    else:
                        dist_y = (obj_pos['y'] - marked_bounds['y_max']) * 100
                
                total_distance = (dist_x**2 + dist_y**2)**0.5
                
                mismatches.append({
                    'constraint': 'location_mismatch',
                    'severity': 'critical',
                    'object': obj_id,
                    'issue_type': 'position_outside_marked_surface',
                    'marked_location': marked_location,
                    'actual_location': actual_surface,
                    'actual_position': obj_pos,
                    'marked_surface_bounds': marked_bounds,
                    'distance_from_bounds_cm': round(total_distance, 1),
                    'expected': f'{obj_id} should be within {marked_location} bounds: x=[{marked_bounds["x_min"]:.2f}, {marked_bounds["x_max"]:.2f}], y=[{marked_bounds["y_min"]:.2f}, {marked_bounds["y_max"]:.2f}]',
                    'actual': f'{obj_id} actual position ({obj_pos["x"]:.2f}, {obj_pos["y"]:.2f}) is {total_distance:.1f}cm away from marked surface',
                    'suggestion': f'Please move {obj_id} to within {marked_location} valid range, suggested position: center ({(marked_bounds["x_min"]+marked_bounds["x_max"])/2:.2f}, {(marked_bounds["y_min"]+marked_bounds["y_max"])/2:.2f})' + 
                                  (f', or re-mark as {actual_surface}' if actual_surface else '')
                })
        
        return {
            'violations': mismatches,
            'count': len(mismatches),
            'passed': len(mismatches) == 0
        }
    
    def _find_surface_containing_position(self, layout: Dict, position: Dict) -> str:
        """
        根据坐标找到包含该位置的work surface
        
        Args:
            layout: 布局JSON
            position: 位置坐标
        
        Returns:
            surface_name: 包含该位置的surface名称，如果没找到返回None
        """
        # 遍历所有floor级别的work surface
        work_surface_names = ['ExperimentalPlatform', 'ValidationPlatform', 'FumeHood', 
                             'ReagentCabinet', 'GloveBox', 'LabBench']
        
        for surface_name in work_surface_names:
            bounds = self._get_surface_bounds(layout, surface_name)
            if bounds:
                if (bounds['x_min'] <= position['x'] <= bounds['x_max'] and
                    bounds['y_min'] <= position['y'] <= bounds['y_max']):
                    return surface_name
        
        return None
    
    def _get_deduction(self, value: float, rules: Dict) -> float:
        """
        根据规则计算扣分
        
        Args:
            value: 违规程度值
            rules: 扣分规则字典
        
        Returns:
            deduction: 扣分值
        """
        for severity in ['severe', 'high', 'medium', 'low']:
            threshold, deduction = rules[severity]
            if value >= threshold:
                return deduction
        return 0
    
    def _is_inside_reagent_cabinet(self, layout: Dict, obj: Dict) -> bool:
        """
        检查物体是否实际在试剂柜内（通过bbox检查）
        
        Args:
            layout: 布局JSON
            obj: 物体对象
        
        Returns:
            bool: 是否在试剂柜内
        """
        asset_pos = obj['position']
        
        # 查找试剂柜
        cabinet_obj = None
        for o in layout.get('objects', []):
            obj_id = o.get('id', '')
            if 'ReagentCabinet' in obj_id or 'reagent_cabinet' in obj_id.lower():
                cabinet_obj = o
                break
        
        if cabinet_obj is None:
            return False
        
        # 获取试剂柜的bbox
        cabinet_pos = cabinet_obj['position']
        cabinet_info = self.asset_loader.get_asset_info('ReagentCabinet')
        if not cabinet_info:
            return False
        
        # 计算试剂柜的边界（bbox检查）
        cabinet_bbox = cabinet_info['geometry']['bbox']
        cabinet_rotation = cabinet_obj.get('rotation', {}).get('z', 0)
        
        # 根据旋转确定试剂柜的实际尺寸
        if cabinet_rotation in [90, 270, -90, -270]:
            cabinet_width = cabinet_bbox['short']
            cabinet_depth = cabinet_bbox['long']
        else:
            cabinet_width = cabinet_bbox['long']
            cabinet_depth = cabinet_bbox['short']
        
        # 试剂柜的边界
        cabinet_x_min = cabinet_pos['x'] - cabinet_width / 2
        cabinet_x_max = cabinet_pos['x'] + cabinet_width / 2
        cabinet_y_min = cabinet_pos['y'] - cabinet_depth / 2
        cabinet_y_max = cabinet_pos['y'] + cabinet_depth / 2
        cabinet_z_min = cabinet_pos['z']
        cabinet_z_max = cabinet_pos['z'] + cabinet_bbox['height']
        
        # 判断物体是否在试剂柜内（3D检查）
        in_cabinet = (
            cabinet_x_min <= asset_pos['x'] <= cabinet_x_max and
            cabinet_y_min <= asset_pos['y'] <= cabinet_y_max and
            cabinet_z_min <= asset_pos['z'] <= cabinet_z_max
        )
        
        return in_cabinet
