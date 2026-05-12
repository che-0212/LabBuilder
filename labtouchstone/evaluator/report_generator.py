"""
报告生成器
生成评估报告（JSON和HTML格式）
"""

import json
from datetime import datetime
from typing import Dict, List
from labtouchstone.evaluator.utils.file_utils import save_json
from labtouchstone.evaluator.utils.asset_loader import AssetLoader
from labtouchstone.evaluator.config import get_grade


class ReportGenerator:
    """评估报告生成器"""
    
    def __init__(self, asset_loader: AssetLoader = None):
        """
        初始化报告生成器
        
        Args:
            asset_loader: 资产加载器（用于获取化学属性）
        """
        self.asset_loader = asset_loader
    
    def generate_report(self, physical_result: Dict, semantic_result: Dict,
                       layout_file: str, protocol_file: str, experiment_name: str) -> Dict:
        """
        生成综合评估报告
        
        Args:
            physical_result: 物理评估结果
            semantic_result: 语义评估结果
            layout_file: 布局文件路径
            protocol_file: 协议文件路径
            experiment_name: 实验名称
        
        Returns:
            report: 完整的评估报告字典
        """
        # 计算总分
        total_score = physical_result['total_score'] + semantic_result['total_score']
        
        # 生成报告
        report = {
            'metadata': {
                'experiment_name': experiment_name,
                'layout_file': layout_file,
                'protocol_file': protocol_file,
                'evaluation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'evaluator_version': '1.0'
            },
            'scores': {
                'total': round(total_score, 1),
                'physical': round(physical_result['total_score'], 1),
                'semantic': round(semantic_result['total_score'], 1),
                'max_score': 100,
                'percentage': round(total_score, 1),
                'grade': get_grade(total_score),
                'passed': total_score >= 60
            },
            'physical_evaluation': physical_result,
            'semantic_evaluation': semantic_result,
            'critical_issues': self._identify_critical_issues(physical_result, semantic_result),
            'improvement_suggestions': self._generate_suggestions(physical_result, semantic_result, layout_file, protocol_file)
        }
        
        return report
    
    def save_report(self, report: Dict, output_path: str):
        """
        保存JSON报告
        
        Args:
            report: 报告字典
            output_path: 输出路径
        """
        save_json(report, output_path, indent=2)
        print(f"评估报告已保存到：{output_path}")
    
    def generate_html_report(self, report: Dict, output_path: str):
        """
        生成HTML格式报告
        
        Args:
            report: 报告字典
            output_path: 输出HTML路径
        """
        html_content = self._build_html(report)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"HTML报告已保存到：{output_path}")
    
    def _identify_critical_issues(self, physical_result: Dict, semantic_result: Dict) -> list:
        """识别关键问题"""
        critical_issues = []
        
        # 从物理评估中提取高严重性违规
        for violation in physical_result.get('violations', []):
            if violation.get('severity') == 'high':
                critical_issues.append({
                    'severity': 'high',
                    'source': 'physical',
                    'category': violation.get('constraint', ''),
                    'description': violation.get('actual', ''),
                    'suggestion': f"期望: {violation.get('expected', '')}"
                })
        
        # 从语义评估中提取低分项
        for item in semantic_result.get('low_score_items', []):
            if item['score'] <= 2:
                critical_issues.append({
                    'severity': 'high',
                    'source': 'semantic',
                    'category': item['category'],
                    'description': item['issue'],
                    'suggestion': f"问题{item['question_id']}需要改进"
                })
        
        return critical_issues
    
    def _generate_auto_fix_for_boundary(self, violation: Dict) -> Dict:
        """为边界违规生成自动修复指令"""
        obj_id = violation.get('object')
        violation_details = violation.get('violation_details', {})
        current_pos = violation.get('current_position', {})
        
        if not violation_details or not current_pos:
            return None
        
        safety_margin_cm = 5  # 5cm安全余量
        
        # 找出主要超出方向（最大超出距离）
        max_direction = max(violation_details.items(), key=lambda x: x[1])
        direction_name, distance_cm = max_direction
        
        if distance_cm <= 0:
            return None  # 没有实际违规
        
        # 计算修复增量（单位：米）
        fix_distance_m = (distance_cm + safety_margin_cm) / 100
        
        # 根据方向确定修复方案
        fix_map = {
            'west': {'axis': 'x', 'delta': +fix_distance_m, 'description': f'向东移动 {distance_cm+safety_margin_cm:.1f}cm'},
            'east': {'axis': 'x', 'delta': -fix_distance_m, 'description': f'向西移动 {distance_cm+safety_margin_cm:.1f}cm'},
            'south': {'axis': 'y', 'delta': +fix_distance_m, 'description': f'向北移动 {distance_cm+safety_margin_cm:.1f}cm'},
            'north': {'axis': 'y', 'delta': -fix_distance_m, 'description': f'向南移动 {distance_cm+safety_margin_cm:.1f}cm'}
        }
        
        fix_action = fix_map.get(direction_name)
        if not fix_action:
            return None
        
        # 计算新坐标
        new_position = current_pos.copy()
        new_position[fix_action['axis']] = round(
            current_pos[fix_action['axis']] + fix_action['delta'], 
            3
        )
        
        return {
            'type': 'boundary_fix',
            'priority': 1,  # 高优先级
            'object_id': obj_id,
            'violation': {
                'direction': direction_name,
                'distance_cm': distance_cm,
                'current_position': current_pos.copy()  # 添加原始位置，用于区分同名对象
            },
            'action': {
                'axis': fix_action['axis'],
                'old_value': current_pos[fix_action['axis']],
                'new_value': new_position[fix_action['axis']],
                'delta': fix_action['delta']
            },
            'description': fix_action['description']
        }
    
    def _generate_auto_fix_for_collision(self, violation: Dict) -> Dict:
        """为碰撞违规生成自动修复指令（改进版）"""
        import math
        
        obj_a_id, obj_b_id = violation.get('objects', [None, None])
        positions = violation.get('positions', {})
        bboxes = violation.get('bboxes', {})
        rotations = violation.get('rotations', {})
        overlap_area = violation.get('overlap_area', 0)
        
        if not all([obj_a_id, obj_b_id, positions, bboxes]):
            return None
        
        # 1. 确定移动优先级：小物体优先、椅子优先
        priority_map = {
            'Chair': 10,
            'Beaker': 9,
            'TestTube': 9,
            'Pipette': 9,
            'GraduatedCylinder': 9,
            'Thermometer': 9,
            'GlassRod': 9,
            'Flask': 8,
            'RoundBottomFlask': 8,
            'GrahamCondenser': 7,
            'SeparatoryFunnel': 7,
            'HeatingPlate': 3,
            'MagneticStirrer': 3,
            'RotaryEvaporator': 2,
            'ExperimentalPlatform': 1,
            'ValidationPlatform': 1,
            'FumeHood': 1,
            'ReagentCabinet': 1,
            'Shelf': 1,
            'Refrigerator': 1
        }
        
        def get_priority(obj_id):
            base_name = obj_id.split('#')[0]  # 去掉索引
            base_name = base_name.split('_')[0]  # 去掉后缀
            return priority_map.get(base_name, 5)
        
        priority_a = get_priority(obj_a_id)
        priority_b = get_priority(obj_b_id)
        
        # 选择移动的对象（优先级高的移动）
        if priority_a > priority_b:
            move_obj = obj_a_id
            fixed_obj = obj_b_id
        else:
            move_obj = obj_b_id
            fixed_obj = obj_a_id
        
        # 2. 计算分离方向和距离
        pos_move = positions[move_obj]
        pos_fixed = positions[fixed_obj]
        
        # 计算两物体中心的向量
        dx = pos_move['x'] - pos_fixed['x']
        dy = pos_move['y'] - pos_fixed['y']
        distance = math.sqrt(dx**2 + dy**2)
        
        # 【改进】完全重叠时使用确定性的随机方向（基于物体ID哈希）
        if distance < 0.001:
            # 使用物体ID的哈希值生成确定性的角度
            # 这样相同的碰撞对总是产生相同的分离方向
            hash_val = hash(move_obj + fixed_obj) % 360
            angle = math.radians(hash_val)
            dx = math.cos(angle)
            dy = math.sin(angle)
            distance = 1.0
        
        # 归一化方向
        dir_x = dx / distance
        dir_y = dy / distance
        
        # 3. 计算需要移动的距离
        # 估算重叠距离：overlap_area ≈ overlap_x * overlap_y
        # 简化：假设移动 sqrt(overlap_area) + 安全余量
        # 【改进】增加最小分离距离，确保物体充分分开
        separation_cm = max(math.sqrt(overlap_area) + 10, 15)  # 至少15cm
        separation_m = separation_cm / 100
        
        # 4. 计算新位置
        new_position = {
            'x': round(pos_move['x'] + dir_x * separation_m, 3),
            'y': round(pos_move['y'] + dir_y * separation_m, 3),
            'z': pos_move.get('z', 0)
        }
        
        return {
            'type': 'collision_fix',
            'priority': 2,  # 中高优先级
            'move_object': move_obj,
            'fixed_object': fixed_obj,
            'violation': {
                'overlap_cm2': overlap_area
            },
            'action': {
                'old_position': pos_move.copy(),
                'new_position': new_position,
                'direction': {'x': dir_x, 'y': dir_y},
                'distance_m': separation_m
            },
            'description': f'移动 {move_obj} 远离 {fixed_obj}（方向[{dir_x:.2f},{dir_y:.2f}]，距离{separation_cm:.1f}cm）'
        }
    
    def _generate_auto_fix_for_chemical_constraint(self, violation: Dict) -> Dict:
        """
        为化学约束违规生成自动修复指令
        
        Args:
            violation: 化学约束违规信息
            
        Returns:
            自动修复指令字典，如果无法生成则返回None
        """
        import re
        
        constraint_type = violation.get('constraint')
        details = violation.get('details', {})
        expected_text = details.get('expected', '')
        actual_text = details.get('actual', '')
        
        # 尝试解析距离约束 (格式: "asset1 and asset2 distance ≥ XXcm")
        expected_match = re.search(r'(\w+)\s*and\s*(\w+)\s*distance\s*≥\s*([\d.]+)', expected_text)
        if expected_match:
            asset1, asset2, required_cm_str = expected_match.groups()
            required_cm = float(required_cm_str)
            
            # 提取当前距离
            actual_match = re.search(r'distance\s*=\s*([\d.]+)', actual_text)
            if actual_match:
                current_cm = float(actual_match.group(1))
                
                # 计算需要增加的距离
                gap_cm = required_cm - current_cm + 10  # 10cm安全余量
                
                if gap_cm > 0:
                    return {
                        'type': 'chemical_separation_fix',
                        'priority': 3,  # 中等优先级（低于边界和碰撞）
                        'constraint_type': constraint_type,
                        'move_object': asset1,  # 假设移动第一个资产
                        'reference_object': asset2,
                        'violation': {
                            'current_distance_cm': current_cm,
                            'required_distance_cm': required_cm,
                            'gap_cm': gap_cm
                        },
                        'action': {
                            'type': 'increase_separation',
                            'additional_distance_cm': gap_cm
                        },
                        'description': f"增加 {asset1} 与 {asset2} 的距离 {gap_cm:.1f}cm (当前 {current_cm:.1f}cm → 目标 {required_cm:.1f}cm)"
                    }
        
        # 尝试解析位置约束 (格式: "asset should be in location")
        location_match = re.search(r'(\w+)\s*should be in\s*(\w+)', expected_text)
        if location_match:
            asset, required_location = location_match.groups()
            
            # 提取当前位置
            actual_location_match = re.search(r'(\w+)\s*is in\s*(\w+)', actual_text)
            if actual_location_match:
                _, current_location = actual_location_match.groups()
                
                return {
                    'type': 'chemical_location_fix',
                    'priority': 3,
                    'constraint_type': constraint_type,
                    'move_object': asset,
                    'violation': {
                        'current_location': current_location,
                        'required_location': required_location
                    },
                    'action': {
                        'type': 'relocate',
                        'target_location': required_location
                    },
                    'description': f"将 {asset} 从 {current_location} 移动到 {required_location}"
                }
        
        # 尝试解析边缘距离约束
        edge_match = re.search(r'(\w+)\s*distance from edge\s*≥\s*([\d.]+)', expected_text)
        if edge_match:
            asset, required_cm_str = edge_match.groups()
            required_cm = float(required_cm_str)
            
            actual_edge_match = re.search(r'edge\s*([\d.]+)', actual_text)
            if actual_edge_match:
                current_cm = float(actual_edge_match.group(1))
                gap_cm = required_cm - current_cm + 5  # 5cm安全余量
                
                if gap_cm > 0:
                    return {
                        'type': 'chemical_edge_fix',
                        'priority': 3,
                        'constraint_type': constraint_type,
                        'move_object': asset,
                        'violation': {
                            'current_edge_distance_cm': current_cm,
                            'required_edge_distance_cm': required_cm,
                            'gap_cm': gap_cm
                        },
                        'action': {
                            'type': 'move_away_from_edge',
                            'additional_distance_cm': gap_cm
                        },
                        'description': f"将 {asset} 远离边缘 {gap_cm:.1f}cm (当前 {current_cm:.1f}cm → 目标 {required_cm:.1f}cm)"
                    }
        
        # 无法解析或生成修复指令
        return None
    
    def _generate_reagent_layering_suggestions(self, layout: Dict, protocol: Dict) -> List[Dict]:
        """
        生成试剂分层建议（基于规则，由LLM执行）
        
        检查所有试剂的位置，生成建议：
        1. 试剂应该存储在 ReagentCabinet
        2. 试剂应该按照化学属性分层：
           - Layer 1 (z=0.8m): 酸类
           - Layer 2 (z=1.1m): 碱类
           - Layer 3 (z=1.3m): 易燃/氧化剂/活泼金属
           - Layer 4 (z=1.5m): 一般试剂
        
        Args:
            layout: 布局JSON
            protocol: 协议JSON
        
        Returns:
            建议列表
        """
        suggestions = []
        
        # 从 asset_loader (assets_annotated.json) 获取试剂属性，而不是从protocol
        # 因为protocol可能没有完整的props信息
        misplaced_reagents = []
        for obj in layout.get('objects', []):
            obj_id = obj.get('id', '')
            
            # 从asset_loader获取试剂属性（优先使用assets_annotated.json）
            props = {}
            if self.asset_loader:
                asset_info = self.asset_loader.get_asset_info(obj_id)
                if asset_info:
                    props = asset_info.get('props', {})
            
            # 如果asset_loader没有找到，尝试从protocol获取（向后兼容）
            if not props:
                obj_name = obj_id.split('_')[0] if '_' in obj_id else obj_id
                for asset in protocol.get('assets', []):
                    if asset.get('type') == 'reagent' and asset.get('name') == obj_name:
                        props = asset.get('props', {})
                        break
            
            # 如果没有找到属性信息，跳过（可能是非试剂对象）
            # 注意：即使没有props，如果对象在reagent_cabinet中，也应该检查分层
            # 所以这里不跳过，而是使用空props（会在后面判断为一般试剂）
            
            # 检查当前位置
            current_location = obj.get('initial_location', '').lower()
            current_z = obj.get('position', {}).get('z', 0)
            
            # 判断是否在试剂柜
            is_in_cabinet = 'reagent' in current_location and 'cabinet' in current_location
            
            # 确定推荐的层级（基于化学属性优先级：acid > base > flammable/oxidizer/reactive_metal > 其他）
            if props.get('acid'):
                recommended_layer = 0.8
                layer_name = 'Layer 1 (Acids)'
            elif props.get('base'):
                recommended_layer = 1.1
                layer_name = 'Layer 2 (Bases)'
            elif props.get('flammable') or props.get('oxidizer') or props.get('reactive_metal'):
                recommended_layer = 1.3
                layer_name = 'Layer 3 (Flammables/Oxidizers/Reactive Metals)'
            else:
                recommended_layer = 1.5
                layer_name = 'Layer 4 (General Reagents)'
            
            # 检查是否需要调整
            needs_relocation = not is_in_cabinet
            needs_layering = is_in_cabinet and abs(current_z - recommended_layer) > 0.05
            
            if needs_relocation or needs_layering:
                misplaced_reagents.append({
                    'name': obj_id,
                    'current_location': current_location if current_location else 'unknown',
                    'current_z': current_z,
                    'recommended_layer': recommended_layer,
                    'layer_name': layer_name,
                    'needs_relocation': needs_relocation,
                    'needs_layering': needs_layering
                })
        
        if not misplaced_reagents:
            return []
        
        # 查找 ReagentCabinet 的位置和边界
        reagent_cabinet_bounds = None
        for obj in layout.get('objects', []):
            if obj.get('id') == 'ReagentCabinet' and obj.get('initial_location') == 'floor':
                # 获取ReagentCabinet的位置
                pos = obj.get('position', {})
                cabinet_x = pos.get('x', 0)
                cabinet_y = pos.get('y', 0)
                
                # 获取ReagentCabinet的尺寸（从asset_loader）
                if self.asset_loader:
                    try:
                        asset_info = self.asset_loader.get_asset_info('ReagentCabinet')
                        if asset_info:
                            bbox = asset_info.get('geometry', {}).get('bbox', {})
                            # bbox values are already in meters, not cm
                            short = bbox.get('short', 0.6)  # default 0.6m if missing
                            long = bbox.get('long', 0.4)    # default 0.4m if missing
                            
                            # 根据旋转计算边界
                            rot_z = obj.get('rotation', {}).get('z', 0)
                            if rot_z in [90, 270]:
                                # 90/270度：long在y方向，short在x方向
                                half_x = short / 2
                                half_y = long / 2
                            else:
                                # 0/180度：long在x方向，short在y方向
                                half_x = long / 2
                                half_y = short / 2
                            
                            # 计算边界，留5cm边缘（确保min < max）
                            margin = 0.05
                            x_min_raw = cabinet_x - half_x + margin
                            x_max_raw = cabinet_x + half_x - margin
                            y_min_raw = cabinet_y - half_y + margin
                            y_max_raw = cabinet_y + half_y - margin
                            
                            reagent_cabinet_bounds = {
                                'x_min': min(x_min_raw, x_max_raw),
                                'x_max': max(x_min_raw, x_max_raw),
                                'y_min': min(y_min_raw, y_max_raw),
                                'y_max': max(y_min_raw, y_max_raw),
                                'center_x': cabinet_x,
                                'center_y': cabinet_y
                            }
                    except Exception:
                        pass
                break
        
        # 生成建议文本
        relocation_items = [r for r in misplaced_reagents if r['needs_relocation']]
        layering_items = [r for r in misplaced_reagents if r['needs_layering'] and not r['needs_relocation']]
        
        suggestion_text = "**Reagent Storage & Layering Recommendation:**\n\n"
        
        # 添加 ReagentCabinet 边界信息
        if reagent_cabinet_bounds:
            suggestion_text += f"**ReagentCabinet Location & Bounds:**\n"
            suggestion_text += f"  - Valid range: x=[{reagent_cabinet_bounds['x_min']:.2f}, {reagent_cabinet_bounds['x_max']:.2f}], "
            suggestion_text += f"y=[{reagent_cabinet_bounds['y_min']:.2f}, {reagent_cabinet_bounds['y_max']:.2f}]\n"
            suggestion_text += f"  - Center: ({reagent_cabinet_bounds['center_x']:.2f}, {reagent_cabinet_bounds['center_y']:.2f})\n\n"
        
        if relocation_items:
            suggestion_text += f"**{len(relocation_items)} reagents should be moved to ReagentCabinet:**\n"
            for item in relocation_items[:5]:  # 最多显示5个
                suggestion_text += f"  - {item['name']} (currently on {item['current_location']}) → ReagentCabinet {item['layer_name']}\n"
            if len(relocation_items) > 5:
                suggestion_text += f"  - ... and {len(relocation_items) - 5} more\n"
            suggestion_text += "\n"
            suggestion_text += "**IMPORTANT: When moving reagents to ReagentCabinet:**\n"
            suggestion_text += "  1. Update the 'position' (x, y, z) to be within ReagentCabinet bounds\n"
            suggestion_text += "  2. Update the 'initial_location' field from 'FumeHood' to 'ReagentCabinet'\n"
            suggestion_text += "  3. Set the correct z-coordinate according to the layer (0.8m, 1.1m, 1.3m, or 1.5m)\n\n"
        
        if layering_items:
            suggestion_text += f"{len(layering_items)} reagents in ReagentCabinet need layer adjustment:\n"
            for item in layering_items[:5]:
                suggestion_text += f"  - {item['name']} (z={item['current_z']:.2f}m) → {item['layer_name']} (z={item['recommended_layer']}m)\n"
            if len(layering_items) > 5:
                suggestion_text += f"  - ... and {len(layering_items) - 5} more\n"
            suggestion_text += "\n"
        
        suggestion_text += """
**4-Layer Organization Rule:**
- Layer 1 (z=0.8m): Acids - heavy, corrosive, separated from bases
- Layer 2 (z=1.1m): Bases - separated from acids to prevent mixing
- Layer 3 (z=1.3m): Flammables, Oxidizers, Reactive Metals - far from acids/bases
- Layer 4 (z=1.5m): General reagents, salts, low-hazard items

**Spatial Arrangement:**
- Distribute reagents across BOTH X and Y axes to maximize space utilization
- Use a 3D grid layout: vary X, Y, and Z positions to avoid collisions
- Maintain ~20cm spacing between adjacent reagents in the same layer
- Prioritize Y-axis distribution (long dimension) over X-axis (short dimension)
"""
        
        suggestions.append({
            'type': 'reagent_layering',
            'severity': 'medium',
            'count': len(misplaced_reagents),
            'details': misplaced_reagents,
            'suggestion': suggestion_text
        })
        
        return suggestions
    
    def _generate_implicit_chemical_hint(self, violation: Dict) -> str:
        """
        生成基于化学属性的隐式安全提示（不包含metric的具体约束）
        
        策略：
        - ❌ 不说：`NaOH should maintain distance from HCl ≥ 150cm`（显式metric规则）
        - ✅ 说：`Consider safe placement of NaOH (corrosive, base) and HCl (corrosive, acid)`（隐式引导）
        
        Args:
            violation: 化学约束违规信息
            
        Returns:
            隐式化学安全提示
        """
        import re
        
        details = violation.get('details', {})
        expected = details.get('expected', '')
        actual = details.get('actual', '')
        
        # 尝试从violation中提取资产名称
        # 常见模式：
        # - "Asset1 should maintain distance from Asset2 ≥ Xcm"
        # - "Asset should be in location"
        # - "Asset distance from edge ≥ Xcm"
        
        assets_with_props = []
        
        # 模式1：分离距离（两个资产）
        distance_match = re.search(r'(\w+)\s+should maintain distance from\s+(\w+)', expected)
        if distance_match:
            asset1, asset2 = distance_match.groups()
            props1 = self._get_asset_props_summary(asset1)
            props2 = self._get_asset_props_summary(asset2)
            
            if props1 or props2:
                reason = "due to potential safety hazards"
                if 'flammable' in props1.lower() and 'heat' in props2.lower():
                    reason = "to prevent fire risk"
                elif 'acid' in props1.lower() and 'base' in props2.lower():
                    reason = "to avoid dangerous reactions"
                elif 'corrosive' in props1.lower() or 'corrosive' in props2.lower():
                    reason = "due to corrosive properties"
                
                return f"[Chemical Safety] Consider safe separation between {asset1} {props1} and {asset2} {props2} {reason}"
            else:
                return f"[Chemical Safety] Ensure {asset1} and {asset2} are placed with appropriate safety distance"
        
        # 模式2：存储位置（单个资产）
        location_match = re.search(r'(\w+)\s+should be in\s+(\w+)', expected)
        if location_match:
            asset, location = location_match.groups()
            props = self._get_asset_props_summary(asset)
            
            if props:
                return f"[Chemical Safety] {asset} {props} should be properly stored in designated area for safety"
            else:
                return f"[Chemical Safety] Ensure {asset} is stored in appropriate location"
        
        # 模式3：边缘距离（单个资产）
        edge_match = re.search(r'(\w+)\s+distance from edge', expected)
        if edge_match:
            asset = edge_match.group(1)
            props = self._get_asset_props_summary(asset)
            
            if props:
                return f"[Chemical Safety] {asset} {props} should be placed away from edges to prevent accidents"
            else:
                return f"[Chemical Safety] Place {asset} away from edges for safety"
        
        # 默认：通用安全提示（不包含具体距离）
        return f"[Chemical Safety] Review chemical safety considerations for this layout"
    
    def _get_asset_props_summary(self, asset_name: str) -> str:
        """
        获取资产的化学属性摘要（用于隐式提示）
        
        Args:
            asset_name: 资产名称
            
        Returns:
            属性摘要字符串，例如"(flammable, volatile)"
        """
        if not self.asset_loader:
            return ""
        
        # 获取资产信息
        asset_info = self.asset_loader.get_asset_info(asset_name)
        if not asset_info:
            return ""
        
        props = asset_info.get('props', {})
        if not props or not isinstance(props, dict):
            return ""
        
        # 提取True的属性
        true_props = [key for key, value in props.items() if value is True]
        
        if not true_props:
            return ""
        
        # 返回括号包围的属性列表
        return f"({', '.join(true_props)})"
    
    def _generate_suggestions(self, physical_result: Dict, semantic_result: Dict, layout_file: str = None, protocol_file: str = None) -> Dict:
        """
        生成改进建议（包含关键修复和自动修复指令）
        
        新结构：
        - priority_order: 修复优先级顺序
        - critical_fixes: 必须由LLM处理的关键问题（location不匹配、高度错误）
        - auto_fixes: 系统可自动修复的简单问题（简单边界、碰撞）
        - optimization: 优化建议（化学约束改进）
        
        Args:
            physical_result: 物理评估结果
            semantic_result: 语义评估结果
            layout_file: 布局文件路径（可选）
            protocol_file: 协议文件路径（可选）
        """
        suggestions = {
            'priority_order': ['critical_fixes', 'auto_fixes', 'optimization'],
            'critical_fixes': [],  # ← 新增：关键修复（必须LLM处理）
            'auto_fixes': [],      # 自动修复指令（系统处理）
            'optimization': [],    # 优化建议
            'immediate': [],       # 向后兼容：立即处理
            'recommended': [],     # 向后兼容：建议改进
            'optional': []         # 向后兼容：可选优化
        }
        
        # === 第一优先级：处理CRITICAL问题（location不匹配、高度错误）===
        physical_constraints = physical_result.get('physical_constraints', {})
        
        # 1. Location-Position不匹配（最高优先级）- 按surface分组
        location_mismatch = physical_constraints.get('location_mismatch', {})
        mismatches_by_surface = {}  # 按marked_location分组
        
        for mismatch in location_mismatch.get('violations', []):
            marked_loc = mismatch['marked_location']
            if marked_loc not in mismatches_by_surface:
                mismatches_by_surface[marked_loc] = []
            mismatches_by_surface[marked_loc].append(mismatch)
        
        # 为每个surface生成一个重新布局的建议
        for surface_name, mismatches in mismatches_by_surface.items():
            object_list = [m['object'] for m in mismatches]
            surface_bounds = mismatches[0].get('marked_surface_bounds', {})
            
            suggestion_text = (
                f"Please re-layout the following {len(object_list)} objects on {surface_name}:"
                f"\n  Object list: {', '.join(object_list)}"
                f"\n  Surface bounds: x=[{surface_bounds.get('x_min', 0):.2f}, {surface_bounds.get('x_max', 0):.2f}], "
                f"y=[{surface_bounds.get('y_min', 0):.2f}, {surface_bounds.get('y_max', 0):.2f}]"
                f"\n  Requirements:"
                f"\n    1. All coordinates must be within the surface bounds"
                f"\n    2. Objects must not collide (maintain at least 10cm spacing)"
                f"\n    3. Z-coordinate must be 0.8m for all objects"
            )
            
            suggestions['critical_fixes'].append({
                'type': 'location_mismatch_batch',
                'priority': 1,
                'severity': 'critical',
                'surface': surface_name,
                'objects': object_list,
                'count': len(object_list),
                'issue': f"{len(object_list)} objects are marked as {surface_name} but coordinates are outside this surface",
                'suggestion': suggestion_text,
                'details': {
                    'surface_bounds': surface_bounds,
                    'mismatches': [
                        {
                            'object': m['object'],
                            'current_position': m['actual_position'],
                            'actual_surface': m.get('actual_location'),
                            'distance_from_marked_cm': m.get('distance_from_bounds_cm', 0)
                        }
                        for m in mismatches
                    ]
                }
            })
        
        # 2. 高度错误（高优先级）- 按surface分组
        height_check = physical_constraints.get('height', {})
        height_errors_by_surface = {}
        
        for violation in height_check.get('violations', []):
            surface = violation.get('initial_location', 'unknown')
            if surface not in height_errors_by_surface:
                height_errors_by_surface[surface] = []
            
            # 解析期望和实际高度
            expected_str = violation.get('expected', 'z = 0.8m')
            actual_str = violation.get('actual', 'z = 0.0m')
            
            # 从字符串中提取数值（格式: "z = 0.8m"）
            try:
                expected_z = float(expected_str.split('=')[1].strip().rstrip('m'))
                actual_z = float(actual_str.split('=')[1].strip().rstrip('m'))
            except:
                expected_z = 0.8
                actual_z = 0.0
            
            height_errors_by_surface[surface].append({
                'object': violation['object'],
                'expected_z': expected_z,
                'actual_z': actual_z,
                'error': violation.get('error', abs(expected_z - actual_z))
            })
        
        # 为每个surface生成一个批量高度修复建议
        for surface, errors in height_errors_by_surface.items():
            object_list = [e['object'] for e in errors]
            expected_z = errors[0]['expected_z'] if errors else 0.8
            
            suggestions['critical_fixes'].append({
                'type': 'height_error_batch',
                'priority': 2,
                'severity': 'critical',
                'surface': surface,
                'objects': object_list,
                'count': len(object_list),
                'issue': f"{len(object_list)} objects have incorrect Z-coordinates",
                'suggestion': f"Please correct the Z-coordinates of the following {len(object_list)} objects to {expected_z:.3f}m:\n  Objects: {', '.join(object_list)}\n  Expected Z: {expected_z:.3f}m",
                'details': {
                    'expected_z': expected_z,
                    'errors': errors
                }
            })
        
        # 收集所有其他违规（避免重复）
        all_violations = []
        seen_violations = set()  # 用于去重
        
        # 从physical_constraints子结构中获取违规（排除已处理的critical问题）
        for constraint_type in ['boundary', 'collision', 'room_assets']:
            constraint_data = physical_constraints.get(constraint_type, {})
            for violation in constraint_data.get('violations', []):
                # 使用对象/约束类型作为去重标识
                obj_key = str(violation.get('object', violation.get('objects', '')))
                constraint_key = violation.get('constraint', '')
                v_key = f"{constraint_key}:{obj_key}"
                
                if v_key not in seen_violations:
                    seen_violations.add(v_key)
                    all_violations.append(violation)
        
        # 收集有location不匹配的物体ID列表（这些不应该生成简单的auto_fix）
        objects_with_location_mismatch = set(
            fix['object'] for fix in suggestions['critical_fixes'] 
            if fix['type'] == 'location_mismatch'
        )
        
        # 从物理违规中提取建议
        seen_fix_keys = set()  # 用于去重修复指令
        for violation in all_violations:
            constraint_type = violation.get('constraint', '')
            severity = violation.get('severity', 'medium')
            obj_id = violation.get('object')
            
            # === 边界违规：只为简单case生成自动修复指令 ===
            if constraint_type in ['boundary_check', 'room_boundary_check']:
                # 如果该物体有location不匹配问题，跳过auto_fix（由LLM的critical_fix处理）
                if obj_id in objects_with_location_mismatch:
                    suggestions['immediate'].append(
                        f"[CRITICAL] {obj_id}: Location标记与坐标不匹配，需要LLM重新布局（见critical_fixes）"
                    )
                    continue
                
                # 简单的边界违规（超出<50cm），生成auto_fix
                out_distance = violation.get('out_of_bounds_distance', 0)
                current_pos = violation.get('current_position', {})
                
                if out_distance < 50:  # 简单case：超出<50cm
                    fix = self._generate_auto_fix_for_boundary(violation)
                    if fix:
                        fix_key = f"boundary:{obj_id}:{current_pos.get('x', 0)}:{current_pos.get('y', 0)}"
                        if fix_key not in seen_fix_keys:
                            seen_fix_keys.add(fix_key)
                            suggestions['auto_fixes'].append(fix)
                            suggestions['immediate'].append(
                                f"[AUTO-FIX] {fix['object_id']}: {fix['description']}"
                            )
                else:
                    # 复杂case：超出很远，需要LLM处理
                    suggestions['immediate'].append(
                        f"[LLM-FIX] {obj_id}: 超出边界{out_distance:.1f}cm（较远），需要LLM重新调整"
                    )
                continue  # 已添加详细建议，跳过通用建议
            
            # === 碰撞违规：生成自动修复指令 ===
            elif constraint_type in ['collision_check', 'room_collision_check']:
                fix = self._generate_auto_fix_for_collision(violation)
                if fix:
                    # 使用移动对象和固定对象作为去重key
                    move_obj = fix.get('move_object')
                    fixed_obj = fix.get('fixed_object')
                    action = fix.get('action', {})
                    old_pos = action.get('old_position', {})
                    fix_key = f"collision:{move_obj}:{fixed_obj}:{old_pos.get('x', 0)}:{old_pos.get('y', 0)}"
                    
                    if fix_key not in seen_fix_keys:
                        seen_fix_keys.add(fix_key)
                        suggestions['auto_fixes'].append(fix)
                        suggestions['immediate'].append(
                            f"[AUTO-FIX] {fix['description']}"
                        )
                    continue  # 已添加详细建议，跳过通用建议
            
            # 通用建议（非自动修复的）
            suggestion = f"{constraint_type}: {violation.get('expected', '')}"
            
            if severity == 'high':
                suggestions['immediate'].append(suggestion)
            else:
                suggestions['recommended'].append(suggestion)
        
        # === 化学约束违规处理（作为optimization建议）===
        chemical_constraints = physical_result.get('chemical_constraints', {})
        chemical_violations = chemical_constraints.get('violations', [])
        
        for violation in chemical_violations:
            # 化学约束违规需要LLM智能优化，不做auto_fix
            constraint_type = violation.get('constraint', '')
            severity = violation.get('severity', 'medium')
            
            # 生成基于属性的隐式引导（而非显式的metric约束）
            implicit_hint = self._generate_implicit_chemical_hint(violation)
            
            suggestions['optimization'].append({
                'type': 'chemical_safety',  # 改名：从constraint变为safety
                'constraint': constraint_type,
                'severity': severity,
                'issue': violation.get('actual', ''),
                'implicit_hint': implicit_hint,  # 隐式提示
                'suggestion': implicit_hint  # 用隐式提示作为建议
            })
            
            # 同时添加到immediate或recommended（向后兼容）
            if severity == 'high':
                suggestions['immediate'].append(implicit_hint)
            else:
                suggestions['recommended'].append(implicit_hint)
        
        # === 试剂分层建议（基于规则生成建议，由LLM执行）===
        if layout_file and protocol_file:
            # 加载布局和协议数据
            try:
                import json
                with open(layout_file, 'r', encoding='utf-8') as f:
                    layout_data = json.load(f)
                with open(protocol_file, 'r', encoding='utf-8') as f:
                    protocol_data = json.load(f)
                
                reagent_layering_suggestions = self._generate_reagent_layering_suggestions(
                    layout_data, 
                    protocol_data
                )
                
                if reagent_layering_suggestions:
                    # 添加到 optimization 类别
                    for suggestion in reagent_layering_suggestions:
                        suggestions['optimization'].append(suggestion)
                        suggestions['recommended'].append(suggestion['suggestion'])
            except Exception as e:
                # 如果加载失败，跳过试剂分层建议
                pass
        
        # 从语义评估中提取建议
        for q in semantic_result.get('questions', []):
            if q['score'] < 4 and q.get('suggestions'):
                for sug in q['suggestions'][:2]:  # 每题最多取2个建议
                    if q['score'] <= 2:
                        suggestions['immediate'].append(f"问题{q['id']}: {sug}")
                    elif q['score'] == 3:
                        suggestions['recommended'].append(f"问题{q['id']}: {sug}")
                    else:
                        suggestions['optional'].append(f"问题{q['id']}: {sug}")
        
        # 按优先级排序
        suggestions['critical_fixes'].sort(key=lambda x: x['priority'])
        suggestions['auto_fixes'].sort(key=lambda x: x['priority'])
        
        # Add fix order explanation
        suggestions['fix_order_explanation'] = """
Fix Priority Order (from high to low):

1. CRITICAL FIXES (Must be fixed first, handled by LLM):
   - Location-Position Mismatch: Objects marked for one surface but positioned elsewhere, need re-layout
   - Height Errors: Incorrect Z-coordinates, need correction to table height (0.8m)
   
2. AUTO FIXES (Automatically fixed by system):
   - Simple boundary violations: Objects extending <50cm beyond bounds, automatically moved back
   - Simple collisions: Two objects overlapping, automatically separated
   
3. OPTIMIZATION (Optimization suggestions, handled by LLM):
   - Chemical constraints: Flammable-heat separation, reagent storage, etc.
   - Semantic improvements: Workflow, accessibility, etc.

Recommendation: Fix CRITICAL FIXES first to ensure correct location and height, then address other issues.
"""
        
        return suggestions
    
    def _build_html(self, report: Dict) -> str:
        """构建HTML报告（简化版）"""
        # 这里提供一个简化的HTML模板
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>布局评估报告 - {report['metadata']['experiment_name']}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1, h2, h3 {{ color: #333; }}
        .score {{ font-size: 48px; font-weight: bold; color: #4CAF50; }}
        .grade {{ font-size: 32px; color: #2196F3; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        .critical {{ background-color: #ffebee; }}
        .warning {{ background-color: #fff3e0; }}
        .good {{ background-color: #e8f5e9; }}
    </style>
</head>
<body>
    <h1>实验室布局评估报告</h1>
    <p><strong>实验：</strong>{report['metadata']['experiment_name']}</p>
    <p><strong>评估时间：</strong>{report['metadata']['evaluation_time']}</p>
    
    <h2>总体评分</h2>
    <div class="score">{report['scores']['total']}/100</div>
    <div class="grade">等级：{report['scores']['grade']}</div>
    <p>物理评估：{report['scores']['physical']}/70</p>
    <p>语义评估：{report['scores']['semantic']}/30</p>
    <p>状态：{'<span style="color:green">通过</span>' if report['scores']['passed'] else '<span style="color:red">不通过</span>'}</p>
    
    <h2>关键问题</h2>
    <ul>
    {''.join(f'<li class="critical">{issue["description"]}</li>' for issue in report['critical_issues'][:5])}
    </ul>
    
    <h2>改进建议</h2>
    <h3>立即处理</h3>
    <ul>
    {''.join(f'<li>{s}</li>' for s in report['improvement_suggestions']['immediate'][:5])}
    </ul>
    
    <p><em>完整报告请查看JSON文件</em></p>
</body>
</html>
"""
        return html

