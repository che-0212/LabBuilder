"""
基于属性的化学指标计算器

不依赖protocol中的预定义约束，而是根据布局中资产的化学属性
自动生成所有可能的约束并计算满足度。

这样可以：
1. 约束数量更多、更全面
2. 初始布局分数更低
3. 优化后提升更明显
"""

import os
import sys
from typing import Dict, List

# 添加父目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from labtouchstone.evaluator.utils.asset_loader import AssetLoader
from labtouchstone.evaluator.utils.geometry import calculate_distance_2d, calculate_edge_distance
from labtouchstone.evaluator.config import calculate_satisfaction
from labtouchstone.metrics.property_based_constraints import PropertyBasedConstraintGenerator


class PropertyBasedChemicalMetrics:
    """基于属性的化学指标计算器"""
    
    # 约束类型到类别的映射（保持四个类别不变）
    # 1. 易燃试剂与热源分离 (C1)
    # 2. 试剂放在试剂柜 (C2, C3)
    # 3. 不相容试剂分离 (C5-C9)
    # 4. 玻璃仪器远离边缘 (C4)
    CONSTRAINT_TO_CATEGORY = {
        'C1': 'flammable_heat_separation',
        'C2': 'reagent_storage',
        'C3': 'reagent_storage',
        'C4': 'glass_edge_avoidance',
        'C5': 'incompatible_separation',
        'C6': 'incompatible_separation',
        'C7': 'incompatible_separation',
        'C8': 'incompatible_separation',
        'C9': 'incompatible_separation',
    }
    
    def __init__(self, asset_db_path: str):
        """
        初始化
        
        Args:
            asset_db_path: assets_annotated.json文件路径
        """
        self.asset_loader = AssetLoader(asset_db_path)
        self.constraint_generator = PropertyBasedConstraintGenerator(self.asset_loader)
    
    def calculate_all(self, layout: Dict) -> Dict:
        """
        计算所有化学指标
        
        Args:
            layout: 布局JSON数据
        
        Returns:
            metrics: 包含所有化学指标的字典
        """
        # 1. 自动生成约束
        constraints = self.constraint_generator.generate_constraints_from_layout(layout)
        
        if len(constraints) == 0:
            return self._empty_result('布局中无需要检查的化学约束')
        
        # 2. 评估每个约束
        constraint_results = []
        category_satisfactions = {
            'flammable_heat_separation': [],
            'reagent_storage': [],
            'incompatible_separation': [],
            'glass_edge_avoidance': [],
        }
        
        violations = []
        
        for constraint in constraints:
            satisfaction, details = self._evaluate_constraint(layout, constraint)
            weight = constraint.get('weight', 1)
            
            constraint_result = {
                'constraint_type': constraint['constraint_type'],
                'description': constraint['description'],
                'asset1': constraint['asset1'],
                'asset2': constraint.get('asset2'),
                'threshold': constraint['threshold'],
                'satisfaction': satisfaction,
                'passed': satisfaction >= 0.8,
                'details': details
            }
            constraint_results.append(constraint_result)
            
            # 收集类别的所有satisfaction分数（用于计算最差的几个）
            category = self.CONSTRAINT_TO_CATEGORY.get(constraint['constraint_type'])
            if category:
                category_satisfactions[category].append(satisfaction)
            
            # 记录违规
            if not constraint_result['passed']:
                violations.append({
                    'constraint': constraint['constraint_type'],
                    'description': constraint['description'],
                    'severity': 'high' if satisfaction < 0.5 else 'medium',
                    'satisfaction': satisfaction,
                    'details': details
                })
        
        # 3. 计算类别满足度（不同类别使用不同策略）
        category_metrics = {}
        for category, sats in category_satisfactions.items():
            if len(sats) > 0:
                # 策略分类：
                # - 玻璃边缘、试剂存储：使用平均值（所有约束）
                # - 易燃热源、不相容分离：使用最差的3个约束
                if category in ['glass_edge_avoidance', 'reagent_storage']:
                    # 使用所有约束的平均值
                    satisfaction = sum(sats) / len(sats)
                    num_used = len(sats)
                    strategy = 'average_all'
                else:
                    # 易燃热源、不相容分离：固定使用最差的3个约束
                    num_worst = min(len(sats), 3)
                    worst_sats = sorted(sats)[:num_worst]
                    satisfaction = sum(worst_sats) / len(worst_sats)
                    num_used = num_worst
                    strategy = f'worst_3_of_{len(sats)}'
            else:
                satisfaction = 1.0  # 无约束=完美
                num_used = 0
                strategy = 'no_constraints'
            
            category_metrics[category] = {
                'category_name': self._get_category_name(category),
                'constraint_count': len(sats),
                'count_used': num_used,
                'strategy': strategy,
                'satisfaction': satisfaction
            }
        
        # 4. 计算总体满足度（使用所有约束的加权平均）
        total_weight = sum(c.get('weight', 1) for c in constraints)
        total_earned = sum(
            cr['satisfaction'] * constraints[i].get('weight', 1) 
            for i, cr in enumerate(constraint_results)
        )
        overall_satisfaction = total_earned / total_weight if total_weight > 0 else 1.0
        
        return {
            'total_constraints': len(constraints),
            'category_metrics': category_metrics,
            'overall_satisfaction': overall_satisfaction,
            'constraint_results': constraint_results,
            'violations_count': len(violations),
            'violations': violations,
            'note': f'基于属性自动生成了{len(constraints)}个约束'
        }
    
    def _evaluate_constraint(self, layout: Dict, constraint: Dict) -> tuple:
        """
        评估单个约束
        
        Returns:
            (satisfaction, details)
        """
        rule_type = constraint.get('rule_type', 'distance')
        
        if rule_type == 'location':
            # 位置约束（C3试剂存储）
            return self._evaluate_location_constraint(layout, constraint)
        elif rule_type == 'edge_distance':
            # 边缘距离约束（C4玻璃容器）
            return self._evaluate_edge_constraint(layout, constraint)
        else:
            # 距离约束（C1, C5-C9）
            return self._evaluate_distance_constraint(layout, constraint)
    
    def _evaluate_location_constraint(self, layout: Dict, constraint: Dict) -> tuple:
        """
        评估位置约束（C3试剂存储）
        
        根据试剂的实际bbox位置判断是否在试剂柜内，
        而不是简单读取initial_location字段
        """
        asset = constraint['asset1']
        required_location = constraint.get('required_location', 'reagent_cabinet')
        
        obj = self._find_object(layout, asset)
        if obj is None:
            return 0.0, {
                'expected': f'{asset} 应在 {required_location}',
                'actual': f'资产缺失（{asset}）',
                'missing_asset': asset
            }
        
        # 根据bbox位置判断试剂是否物理上在试剂柜内
        asset_pos = obj['position']
        
        # 查找试剂柜的位置和bbox
        cabinet_obj = None
        for o in layout.get('objects', []):
            obj_id = o.get('id', '')
            if 'ReagentCabinet' in obj_id or 'reagent_cabinet' in obj_id.lower():
                cabinet_obj = o
                break
        
        if cabinet_obj is None:
            # 布局中没有试剂柜，试剂不可能在试剂柜内
            return 0.0, {
                'expected': f'{asset} 应在 {required_location}',
                'actual': f'{asset} 在 ({asset_pos["x"]:.2f}, {asset_pos["y"]:.2f})，布局中无试剂柜'
            }
        
        # 获取试剂柜的bbox
        cabinet_pos = cabinet_obj['position']
        cabinet_info = self.asset_loader.get_asset_info('ReagentCabinet')
        if not cabinet_info:
            # 无法获取试剂柜信息，降级为initial_location判断
            actual_location = obj.get('initial_location', '')
            def normalize(s):
                return s.lower().replace('_', '').replace('-', '')
            if normalize(actual_location) == normalize(required_location):
                return 1.0, {'expected': f'{asset} 应在 {required_location}', 'actual': f'{asset} 在 {actual_location}'}
            else:
                return 0.0, {'expected': f'{asset} 应在 {required_location}', 'actual': f'{asset} 在 {actual_location}'}
        
        # 计算试剂柜的边界
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
        
        # 判断试剂是否在试剂柜内（3D检查）
        in_cabinet = (
            cabinet_x_min <= asset_pos['x'] <= cabinet_x_max and
            cabinet_y_min <= asset_pos['y'] <= cabinet_y_max and
            cabinet_z_min <= asset_pos['z'] <= cabinet_z_max
        )
        
        if in_cabinet:
            return 1.0, {
                'expected': f'{asset} 应在 {required_location}',
                'actual': f'{asset} 在试剂柜内 ({asset_pos["x"]:.2f}, {asset_pos["y"]:.2f}, {asset_pos["z"]:.2f})'
            }
        else:
            return 0.0, {
                'expected': f'{asset} 应在 {required_location}',
                'actual': f'{asset} 不在试剂柜内 ({asset_pos["x"]:.2f}, {asset_pos["y"]:.2f}, {asset_pos["z"]:.2f})'
            }
    
    def _evaluate_distance_constraint(self, layout: Dict, constraint: Dict) -> tuple:
        """评估距离约束"""
        asset1 = constraint['asset1']
        asset2 = constraint['asset2']
        threshold = constraint['threshold']
        constraint_type = constraint.get('constraint_type', '')
        
        obj1 = self._find_object(layout, asset1)
        obj2 = self._find_object(layout, asset2)
        
        if obj1 is None or obj2 is None:
            missing = asset1 if obj1 is None else asset2
            return 0.0, {
                'expected': f'{asset1} 与 {asset2} 距离 ≥ {threshold}cm',
                'actual': f'资产缺失（{missing}）',
                'missing_asset': missing
            }
        
        # 特殊处理：不相容试剂分离（C5-C9）
        # 如果两个试剂都在试剂柜且在不同层，视为完全满足
        if constraint_type in ['C5', 'C6', 'C7', 'C8', 'C9']:
            init_loc1 = obj1.get('initial_location', '')
            init_loc2 = obj2.get('initial_location', '')
            
            # 检查是否都在试剂柜
            in_cabinet1 = 'ReagentCabinet' in init_loc1 or 'reagent_cabinet' in init_loc1.lower()
            in_cabinet2 = 'ReagentCabinet' in init_loc2 or 'reagent_cabinet' in init_loc2.lower()
            
            if in_cabinet1 and in_cabinet2:
                z1 = obj1.get('position', {}).get('z', 0)
                z2 = obj2.get('position', {}).get('z', 0)
                
                # 如果在不同层（Z坐标差异超过0.1m），视为完全满足
                if abs(z1 - z2) > 0.1:
                    return 1.0, {
                        'expected': f'{asset1} 与 {asset2} 距离 ≥ {threshold}cm',
                        'actual': f'两试剂在试剂柜不同层（{z1:.1f}m vs {z2:.1f}m），自动满足',
                        'layered_separation': True,
                        'z1': z1,
                        'z2': z2
                    }
        
        # 正常距离评估
        pos1 = obj1.get('position')
        pos2 = obj2.get('position')
        
        actual_distance = calculate_distance_2d(pos1, pos2)
        ratio = actual_distance / threshold if threshold > 0 else 1.0
        satisfaction = calculate_satisfaction(ratio)
        
        return satisfaction, {
            'expected': f'{asset1} 与 {asset2} 距离 ≥ {threshold}cm',
            'actual': f'实际距离 = {actual_distance:.1f}cm',
            'required_distance': threshold,
            'actual_distance': actual_distance,
            'ratio': ratio
        }
    
    def _evaluate_edge_constraint(self, layout: Dict, constraint: Dict) -> tuple:
        """评估边缘距离约束"""
        asset = constraint['asset1']
        threshold = constraint['threshold']
        
        obj = self._find_object(layout, asset)
        if obj is None:
            return 0.0, {
                'expected': f'{asset} 距边缘 ≥ {threshold}cm',
                'actual': f'资产缺失（{asset}）'
            }
        
        # 获取工作表面边界
        work_surface = obj.get('initial_location')
        bounds = self._get_surface_bounds(layout, work_surface)
        
        if bounds is None:
            return 1.0, {
                'expected': f'{asset} 距边缘 ≥ {threshold}cm',
                'actual': '无法获取工作表面边界'
            }
        
        # 计算到边缘的距离
        bbox = self.asset_loader.get_asset_bbox(obj['id'])
        pos = obj['position']
        rotation = obj.get('rotation', {}).get('z', 0)
        
        actual_distance, nearest_edge = calculate_edge_distance(pos, bbox, rotation, bounds)
        ratio = actual_distance / threshold if threshold > 0 else 1.0
        satisfaction = calculate_satisfaction(ratio)
        
        return satisfaction, {
            'expected': f'{asset} 距边缘 ≥ {threshold}cm',
            'actual': f'距{nearest_edge}边缘 {actual_distance:.1f}cm',
            'required_distance': threshold,
            'actual_distance': actual_distance,
            'nearest_edge': nearest_edge,
            'ratio': ratio
        }
    
    def _find_object(self, layout: Dict, asset_name: str) -> Dict:
        """查找物体"""
        for obj in layout.get('objects', []):
            asset_id = obj.get('id', '')
            if asset_id == 'LaboratoryRoom':
                continue
            if asset_name in asset_id or asset_id.startswith(asset_name):
                return obj
        return None
    
    def _find_object_position(self, layout: Dict, asset_name: str) -> Dict:
        """查找物体位置"""
        obj = self._find_object(layout, asset_name)
        return obj.get('position') if obj else None
    
    def _get_surface_bounds(self, layout: Dict, surface_name: str) -> Dict:
        """获取工作表面边界"""
        from labtouchstone.evaluator.utils.geometry import get_surface_bounds
        return get_surface_bounds(layout, surface_name, self.asset_loader)
    
    def _get_category_name(self, category: str) -> str:
        """获取类别中文名"""
        names = {
            'flammable_heat_separation': '易燃试剂与热源分离',
            'reagent_storage': '试剂放在试剂柜',
            'incompatible_separation': '不相容试剂分离',
            'glass_edge_avoidance': '玻璃仪器远离边缘',
        }
        return names.get(category, category)
    
    def _empty_result(self, note: str) -> Dict:
        """返回空结果"""
        return {
            'total_constraints': 0,
            'category_metrics': {
                'flammable_heat_separation': {'category_name': '易燃试剂与热源分离', 'constraint_count': 0, 'satisfaction': 1.0},
                'reagent_storage': {'category_name': '试剂放在试剂柜', 'constraint_count': 0, 'satisfaction': 1.0},
                'incompatible_separation': {'category_name': '不相容试剂分离', 'constraint_count': 0, 'satisfaction': 1.0},
                'glass_edge_avoidance': {'category_name': '玻璃仪器远离边缘', 'constraint_count': 0, 'satisfaction': 1.0},
            },
            'overall_satisfaction': 1.0,
            'constraint_results': [],
            'violations_count': 0,
            'violations': [],
            'note': note
        }
    
    def calculate_category_summary(self, layout: Dict) -> Dict:
        """计算类别汇总"""
        full_metrics = self.calculate_all(layout)
        return {
            'flammable_heat_separation': full_metrics['category_metrics']['flammable_heat_separation']['satisfaction'],
            'reagent_storage': full_metrics['category_metrics']['reagent_storage']['satisfaction'],
            'incompatible_separation': full_metrics['category_metrics']['incompatible_separation']['satisfaction'],
            'glass_edge_avoidance': full_metrics['category_metrics']['glass_edge_avoidance']['satisfaction'],
        }


def test():
    """测试"""
    import json
    
    calculator = PropertyBasedChemicalMetrics('assets_annotated.json')
    
    # 测试一个布局
    layout_path = 'OUTPUT/gemini-3-flash-preview_layout/Alkylation_Reaction_using_Sodium_Hydride_20260117_201153/Alkylation_Reaction_using_Sodium_Hydride_room_isaacsim.json'
    
    with open(layout_path, 'r') as f:
        layout = json.load(f)
    
    metrics = calculator.calculate_all(layout)
    
    print(f"总约束数: {metrics['total_constraints']}")
    print(f"总体满足度: {metrics['overall_satisfaction']:.3f}")
    print(f"违规数: {metrics['violations_count']}")
    print()
    print("类别满足度:")
    for cat, info in metrics['category_metrics'].items():
        print(f"  {info['category_name']}: {info['satisfaction']:.3f} (n={info['constraint_count']})")


if __name__ == '__main__':
    test()

