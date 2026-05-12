"""
化学约束检查器
使用CSP约束满足评分方法检查化学安全约束
"""

from typing import Dict, List, Optional
from labtouchstone.evaluator.utils.geometry import calculate_distance_2d, calculate_edge_distance, calculate_position_ratio
from labtouchstone.evaluator.utils.asset_loader import AssetLoader
from labtouchstone.evaluator.config import CHEMICAL_CONSTRAINTS, calculate_satisfaction


class ChemicalConstraintChecker:
    """化学约束检查器（CSP评分）"""
    
    def __init__(self, asset_loader: AssetLoader):
        """
        初始化化学约束检查器
        
        Args:
            asset_loader: 资产加载器实例
        """
        self.asset_loader = asset_loader
        self.config = CHEMICAL_CONSTRAINTS
        self.max_score = 35
    
    def check_all(self, layout: Dict, protocol: Dict) -> Dict:
        """
        检查所有化学约束（动态分配分值）
        
        在优化阶段：
        - 只使用LLM生成的约束或protocol中的约束
        - 不使用metric的C1-C10约束（保持独立性）
        
        Args:
            layout: 布局JSON
            protocol: 实验协议JSON
        
        Returns:
            result: 包含得分和详细信息的字典
        """
        # 优先使用LLM生成的约束
        llm_constraints = protocol.get('llm_generated_constraints', [])
        standard_constraints = protocol.get('chemical_constraints', [])
        
        # 先检查LLM/标准约束
        if llm_constraints:
            # 使用LLM生成的约束
            result = self._check_llm_constraints(layout, llm_constraints)
        elif standard_constraints:
            # 回退到标准约束（向后兼容）
            result = self._check_standard_constraints(layout, standard_constraints)
        else:
            # 无约束
            result = {
                'score': self.max_score,
                'max_score': self.max_score,
                'constraint_results': [],
                'violations': [],
                'note': '本实验无化学安全约束'
            }
        
        return result
    
    def _check_llm_constraints(self, layout: Dict, llm_constraints: List[Dict]) -> Dict:
        """
        检查LLM生成的约束
        
        LLM约束格式支持：
        - min_distance_cm: 最小分离距离（cm）
        - required_zone: 要求的位置区域
        - min_edge_distance_cm: 距离边缘的最小距离（cm）
        """
        if len(llm_constraints) == 0:
            return {
                'score': self.max_score,
                'max_score': self.max_score,
                'constraint_results': [],
                'violations': [],
                'note': '本实验无化学安全约束'
            }
        
        # 每个LLM约束5分，动态计算总分
        score_per_constraint = 5
        max_score = len(llm_constraints) * score_per_constraint
        
        result = {
            'score': 0,
            'max_score': max_score,
            'constraint_results': [],
            'violations': []
        }
        
        for constraint in llm_constraints:
            constraint_type = constraint.get('constraint_type', 'unknown')
            
            # 根据约束字段确定约束类别并评估
            satisfaction, details = self._evaluate_llm_constraint(layout, constraint)
            
            # 计算得分
            earned_score = satisfaction * score_per_constraint
            result['score'] += earned_score
            
            # 记录结果
            constraint_result = {
                'constraint_type': constraint_type,
                'description': constraint.get('description', ''),
                'allocated_score': score_per_constraint,
                'satisfaction': satisfaction,
                'earned_score': earned_score,
                'passed': satisfaction >= 0.8,
                'details': details,
                'reason': constraint.get('reason', '')
            }
            result['constraint_results'].append(constraint_result)
            
            # 如果未通过，记录为违规
            if not constraint_result['passed']:
                violation = {
                    'constraint': constraint_type,
                    'description': constraint.get('description', ''),
                    'severity': 'high' if satisfaction < 0.5 else 'medium',
                    'expected': details.get('expected'),
                    'actual': details.get('actual'),
                    'satisfaction': satisfaction
                }
                result['violations'].append(violation)
        
        return result
    
    def _check_standard_constraints(self, layout: Dict, constraints: List[Dict]) -> Dict:
        """检查标准化学约束（C1-C10）"""
        if len(constraints) == 0:
            return {
                'score': self.max_score,
                'max_score': self.max_score,
                'constraint_results': [],
                'violations': [],
                'note': '本实验无化学安全约束'
            }
        
        # 动态分配分值
        constraint_scores = self._allocate_scores(constraints)
        
        # 逐个检查约束
        result = {
            'score': 0,
            'max_score': self.max_score,
            'constraint_allocation': constraint_scores,
            'constraint_results': [],
            'violations': []
        }
        
        for constraint in constraints:
            constraint_type = constraint['constraint_type']
            allocated_score = constraint_scores.get(constraint_type, 0)
            
            # 计算约束满足度
            satisfaction, details = self._evaluate_constraint(layout, constraint)
            
            # 计算得分 = 满足度 × 分配分值
            earned_score = satisfaction * allocated_score
            result['score'] += earned_score
            
            # 记录结果
            constraint_result = {
                'constraint_type': constraint_type,
                'description': constraint.get('description', ''),
                'allocated_score': allocated_score,
                'satisfaction': satisfaction,
                'earned_score': earned_score,
                'passed': satisfaction >= 0.8,  # 80%以上算通过
                'details': details
            }
            result['constraint_results'].append(constraint_result)
            
            # 如果未通过，记录为违规
            if satisfaction < 0.8:
                violation = {
                    'constraint': constraint_type,
                    'severity': 'high' if satisfaction < 0.5 else 'medium',
                    'description': constraint.get('description', ''),
                    'expected': details.get('expected', ''),
                    'actual': details.get('actual', ''),
                    'satisfaction': satisfaction,
                    'deduction': allocated_score - earned_score,
                    'assets': constraint.get('asset1') if 'asset1' in constraint else []
                }
                if 'asset2' in constraint:
                    violation['assets'] = [constraint['asset1'], constraint['asset2']]
                else:
                    violation['assets'] = [constraint.get('asset1', '')]
                
                result['violations'].append(violation)
        
        # 【新增】检查chemical_constraints中提到的所有试剂是否都在布局中
        # 如果试剂在约束中被提及但不在布局中，添加C3违规
        mentioned_reagents = set()
        for constraint in constraints:
            if 'asset1' in constraint:
                asset1 = constraint['asset1']
                # 判断是否为试剂（试剂名通常以大写字母开头，且不是仪器）
                if self._is_likely_reagent(asset1):
                    mentioned_reagents.add(asset1)
            if 'asset2' in constraint:
                asset2 = constraint['asset2']
                if self._is_likely_reagent(asset2):
                    mentioned_reagents.add(asset2)
        
        # 检查这些试剂是否在布局中
        missing_reagents = []
        for reagent in mentioned_reagents:
            pos = self._find_object_position(layout, reagent)
            if pos is None:
                missing_reagents.append(reagent)
        
        # 为每个缺失的试剂添加C3违规
        if missing_reagents:
            # 计算C3的分配分数（如果已有C3约束）
            c3_score = constraint_scores.get('C3', 0)
            if c3_score == 0:
                # 如果没有C3约束，分配默认分数
                c3_score = self.max_score * 0.2  # 20%的分数
            
            # 平均分配给每个缺失试剂
            score_per_missing = c3_score / len(missing_reagents) if len(missing_reagents) > 0 else 0
            
            for reagent in missing_reagents:
                # 添加违规记录
                violation = {
                    'constraint': 'C3',
                    'severity': 'high',
                    'description': f'Reagent {reagent} missing from layout',
                    'expected': f'{reagent} should be in reagent_cabinet',
                    'actual': f'Reagent missing ({reagent} not in layout), violates reagent storage constraint',
                    'satisfaction': 0.0,
                    'deduction': score_per_missing,
                    'assets': [reagent],
                    'missing_asset': reagent
                }
                result['violations'].append(violation)
                
                # 添加到constraint_results
                constraint_result = {
                    'constraint_type': 'C3',
                    'description': f'All reagents must be stored in reagent cabinet (missing: {reagent})',
                    'allocated_score': score_per_missing,
                    'satisfaction': 0.0,
                    'earned_score': 0.0,
                    'passed': False,
                    'details': {
                        'expected': f'{reagent} should be in reagent_cabinet',
                        'actual': f'Reagent missing ({reagent} not in layout), violates reagent storage constraint',
                        'missing_asset': reagent
                    }
                }
                result['constraint_results'].append(constraint_result)
                
                # 从总分中扣除
                result['score'] -= score_per_missing
        
        result['score'] = max(0, min(self.max_score, result['score']))
        
        return result
    
    def _is_likely_reagent(self, name: str) -> bool:
        """
        判断名称是否可能是试剂（而不是仪器）
        
        Args:
            name: 资产名称
            
        Returns:
            True if likely a reagent
        """
        # 如果名称为None，不是试剂
        if name is None:
            return False
        
        # 常见仪器关键词
        instrument_keywords = [
            'Flask', 'Beaker', 'Plate', 'Condenser', 'Funnel', 
            'Column', 'Evaporator', 'Stirrer', 'Thermometer',
            'Cylinder', 'Pipette', 'Scale', 'Spatula', 'Rod',
            'Tube', 'Dish', 'Vial', 'Bottle'
        ]
        
        # 如果名称包含仪器关键词，可能不是试剂
        for keyword in instrument_keywords:
            if keyword in name:
                return False
        
        # 否则假设是试剂
        return True
    
    def _allocate_scores(self, constraints: List[Dict]) -> Dict[str, float]:
        """
        动态分配化学约束分值
        
        Args:
            constraints: 约束列表
        
        Returns:
            scores: {constraint_type: allocated_score}
        """
        # 统计约束类型
        constraint_types = [c['constraint_type'] for c in constraints]
        
        # 计算总权重
        total_weight = sum(
            self.config.get(ct, {}).get('weight', 5)
            for ct in constraint_types
        )
        
        if total_weight == 0:
            return {}
        
        # 按比例分配分数
        scores = {}
        for ct in set(constraint_types):
            weight = self.config.get(ct, {}).get('weight', 5)
            count = constraint_types.count(ct)
            
            # 该类型约束的总分配 = (权重 × 实例数 / 总权重) × 总分
            # 然后平均分配给每个实例
            type_total_score = self.max_score * weight * count / total_weight
            scores[ct] = type_total_score / count
        
        return scores
    
    def _evaluate_constraint(self, layout: Dict, constraint: Dict) -> tuple[float, Dict]:
        """
        评估单个约束的满足度（CSP评分核心）
        
        Args:
            layout: 布局JSON
            constraint: 约束定义
        
        Returns:
            (satisfaction, details): 满足度（0-1）和详细信息
        """
        constraint_type = constraint['constraint_type']
        constraint_config = self.config.get(constraint_type, {})
        ctype = constraint_config.get('type')
        
        if ctype == 'distance':
            # 距离类约束（C1, C5-C9）
            return self._evaluate_distance_constraint(layout, constraint, constraint_config)
        
        elif ctype == 'location':
            # 位置类约束（C2, C3）
            return self._evaluate_location_constraint(layout, constraint, constraint_config)
        
        elif ctype == 'edge_distance':
            # 边缘距离约束（C4）
            return self._evaluate_edge_constraint(layout, constraint, constraint_config)
        
        elif ctype == 'zone':
            # 功能分区约束（C10）
            return self._evaluate_zone_constraint(layout, constraint, constraint_config)
        
        else:
            # 未知约束类型，默认通过
            return 1.0, {'expected': '未知约束类型', 'actual': '跳过检查'}
    
    def _evaluate_llm_constraint(self, layout: Dict, constraint: Dict) -> tuple[float, Dict]:
        """
        评估LLM生成的约束
        
        根据约束中的字段自动确定约束类型并评估
        """
        # 确定约束类型
        if 'min_distance_cm' in constraint and constraint.get('asset2'):
            # 距离约束：两个资产之间的距离
            asset1 = constraint['asset1']
            asset2 = constraint['asset2']
            required_distance = constraint['min_distance_cm']
            
            pos1 = self._find_object_position(layout, asset1)
            pos2 = self._find_object_position(layout, asset2)
            
            if pos1 is None or pos2 is None:
                missing_asset = asset1 if pos1 is None else asset2
                return 0.0, {
                    'expected': f'{asset1} and {asset2} distance ≥ {required_distance}cm',
                    'actual': f'Reagent missing ({missing_asset}), cannot satisfy constraint'
                }
            
            actual_distance = calculate_distance_2d(pos1, pos2)
            # 防止除零错误
            if required_distance <= 0:
                ratio = 1.0 if actual_distance > 0 else 0.0
            else:
                ratio = actual_distance / required_distance
            satisfaction = calculate_satisfaction(ratio)
            
            return satisfaction, {
                'expected': f'{asset1} 与 {asset2} 距离 ≥ {required_distance}cm',
                'actual': f'距离 = {actual_distance:.1f}cm',
                'required_distance': required_distance,
                'actual_distance': actual_distance,
                'ratio': ratio
            }
        
        elif 'required_zone' in constraint:
            # 位置约束：资产必须在指定区域
            asset = constraint['asset1']
            required_location = constraint['required_zone']
            
            actual_location = self._find_object_work_surface(layout, asset)
            
            if actual_location is None:
                return 0.0, {
                    'expected': f'{asset} should be in {required_location}',
                    'actual': f'Reagent missing ({asset} not in layout), violates reagent storage constraint'
                }
            
            # 位置约束是二元的（满足或不满足）
            # 使用标准化比较
            def normalize(s):
                return s.lower().replace('_', '').replace('-', '')
            
            if normalize(actual_location) == normalize(required_location):
                satisfaction = 1.0
                details = {
                    'expected': f'{asset} should be in {required_location}',
                    'actual': f'{asset} is in {actual_location}'
                }
            else:
                satisfaction = 0.0
                details = {
                    'expected': f'{asset} should be in {required_location}',
                    'actual': f'{asset} is in {actual_location}, does not meet requirements'
                }
            
            return satisfaction, details
        
        elif 'min_edge_distance_cm' in constraint:
            # 边缘距离约束：距离边缘的距离
            asset = constraint['asset1']
            required_distance = constraint['min_edge_distance_cm']
            
            # 查找物体
            obj = self._find_object(layout, asset)
            if obj is None:
                return 0.0, {
                    'expected': f'{asset} distance from edge ≥ {required_distance}cm',
                    'actual': f'{asset} not in layout'
                }
            
            # 获取工作表面边界
            work_surface = obj['initial_location']
            bounds = self._get_surface_bounds(layout, work_surface)
            
            if bounds is None:
                # 无法确定工作面，默认通过
                return 1.0, {
                    'expected': f'{asset} distance from edge ≥ {required_distance}cm',
                    'actual': 'Unable to get work surface bounds'
                }
            
            # 计算到边缘的距离
            bbox = self.asset_loader.get_asset_bbox(obj['id'])
            pos = obj['position']
            rotation = obj['rotation']['z']
            
            actual_distance, nearest_edge = calculate_edge_distance(pos, bbox, rotation, bounds)
            
            # 计算满足度
            ratio = actual_distance / required_distance
            satisfaction = calculate_satisfaction(ratio)
            
            return satisfaction, {
                'expected': f'{asset} distance from edge ≥ {required_distance}cm',
                'actual': f'{nearest_edge} edge {actual_distance:.1f}cm',
                'required_distance': required_distance,
                'actual_distance': actual_distance,
                'nearest_edge': nearest_edge,
                'ratio': ratio
            }
        
        else:
            # 无法识别的约束类型，默认通过
            return 1.0, {
                'expected': '无法识别的约束类型',
                'actual': '跳过检查'
            }
    
    def _evaluate_distance_constraint(self, layout: Dict, constraint: Dict, 
                                     config: Dict) -> tuple[float, Dict]:
        """
        评估距离类约束
        
        Args:
            layout: 布局JSON
            constraint: 约束定义
            config: 约束配置
        
        Returns:
            (satisfaction, details)
        """
        asset1 = constraint.get('asset1')
        asset2 = constraint.get('asset2')
        required_distance = config.get('threshold', 50)  # cm
        
        # 查找物体位置
        pos1 = self._find_object_position(layout, asset1)
        pos2 = self._find_object_position(layout, asset2)
        
        if pos1 is None or pos2 is None:
            # 【修复】物体不存在时，返回0.0（约束不满足）
            # 缺失的试剂既不在试剂柜，也无法满足分离要求
            missing_asset = asset1 if pos1 is None else asset2
            return 0.0, {
                'expected': f'{asset1} and {asset2} distance ≥ {required_distance}cm',
                'actual': f'Reagent missing ({missing_asset}), cannot satisfy constraint',
                'missing_asset': missing_asset
            }
        
        # 计算实际距离
        actual_distance = calculate_distance_2d(pos1, pos2)
        
        # 计算满足度
        ratio = actual_distance / required_distance
        satisfaction = calculate_satisfaction(ratio)
        
        return satisfaction, {
            'expected': f'{asset1} and {asset2} distance ≥ {required_distance}cm',
            'actual': f'distance = {actual_distance:.1f}cm',
            'required_distance': required_distance,
            'actual_distance': actual_distance,
            'ratio': ratio
        }
    
    def _evaluate_location_constraint(self, layout: Dict, constraint: Dict,
                                     config: Dict) -> tuple[float, Dict]:
        """
        评估位置类约束（C3试剂存储）
        
        使用bbox检查试剂是否物理上在试剂柜内，而不是简单读取initial_location标签
        
        Args:
            layout: 布局JSON
            constraint: 约束定义
            config: 约束配置
        
        Returns:
            (satisfaction, details)
        """
        asset = constraint.get('asset1')
        required_location = config.get('required_location', 'reagent_cabinet')
        
        obj = self._find_object(layout, asset)
        if obj is None:
            return 0.0, {
                'expected': f'{asset} should be in {required_location}',
                'actual': f'Reagent missing ({asset} not in layout), violates reagent storage constraint',
                'missing_asset': asset
            }
        
        # 使用bbox检查：判断试剂是否物理上在试剂柜内
        asset_pos = obj['position']
        
        # 查找试剂柜
        cabinet_obj = None
        for o in layout.get('objects', []):
            obj_id = o.get('id', '')
            if 'ReagentCabinet' in obj_id or 'reagent_cabinet' in obj_id.lower():
                cabinet_obj = o
                break
        
        if cabinet_obj is None:
            # 布局中没有试剂柜
            return 0.0, {
                'expected': f'{asset} should be in {required_location}',
                'actual': f'{asset} at ({asset_pos["x"]:.2f}, {asset_pos["y"]:.2f}), but no reagent cabinet in layout',
                'required_location': required_location,
                'actual_location': 'no_cabinet'
            }
        
        # 获取试剂柜的bbox
        cabinet_pos = cabinet_obj['position']
        cabinet_info = self.asset_loader.get_asset_info('ReagentCabinet')
        if not cabinet_info:
            # 降级为标签判断
            actual_location = obj.get('initial_location', '')
            def normalize(s):
                return s.lower().replace('_', '').replace('-', '')
            if normalize(actual_location) == normalize(required_location):
                return 1.0, {
                    'expected': f'{asset} should be in {required_location}',
                    'actual': f'{asset} is in {actual_location} (label-based)',
                    'required_location': required_location,
                    'actual_location': actual_location
                }
            else:
                return 0.0, {
                    'expected': f'{asset} should be in {required_location}',
                    'actual': f'{asset} is in {actual_location} (label-based)',
                    'required_location': required_location,
                    'actual_location': actual_location
                }
        
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
        
        # 判断试剂是否在试剂柜内（3D检查）
        in_cabinet = (
            cabinet_x_min <= asset_pos['x'] <= cabinet_x_max and
            cabinet_y_min <= asset_pos['y'] <= cabinet_y_max and
            cabinet_z_min <= asset_pos['z'] <= cabinet_z_max
        )
        
        if in_cabinet:
            return 1.0, {
                'expected': f'{asset} should be in {required_location}',
                'actual': f'{asset} is inside reagent cabinet ({asset_pos["x"]:.2f}, {asset_pos["y"]:.2f}, {asset_pos["z"]:.2f})',
                'required_location': required_location,
                'actual_location': 'reagent_cabinet'
            }
        else:
            # 找出试剂实际在哪里（用于提示）
            actual_location = obj.get('initial_location', 'unknown')
            return 0.0, {
                'expected': f'{asset} should be in {required_location}',
                'actual': f'{asset} is outside reagent cabinet at ({asset_pos["x"]:.2f}, {asset_pos["y"]:.2f}, {asset_pos["z"]:.2f}), labeled as {actual_location}',
                'required_location': required_location,
                'actual_location': actual_location
            }
    
    def _evaluate_edge_constraint(self, layout: Dict, constraint: Dict,
                                  config: Dict) -> tuple[float, Dict]:
        """
        评估边缘距离约束（C4）
        
        特殊处理：如果物体实际在试剂柜内（通过bbox检查），则自动满足，
        因为试剂柜内的物品不需要满足边缘距离要求
        
        Args:
            layout: 布局JSON
            constraint: 约束定义
            config: 约束配置
        
        Returns:
            (satisfaction, details)
        """
        asset = constraint.get('asset1')
        required_distance = config.get('threshold', 20)  # cm
        
        # 查找物体
        obj = self._find_object(layout, asset)
        if obj is None:
            return 0.0, {
                'expected': f'{asset} distance from edge ≥ {required_distance}cm',
                'actual': f'Object not found (missing: {asset}), cannot satisfy constraint'
            }
        
        # 检查物体是否实际在试剂柜内（通过bbox检查）
        if self._is_inside_reagent_cabinet_bbox(layout, obj):
            # 试剂在试剂柜内，自动满足边缘距离要求
            pos = obj['position']
            return 1.0, {
                'expected': f'{asset} distance from edge ≥ {required_distance}cm',
                'actual': f'{asset} is inside reagent cabinet ({pos["x"]:.2f}, {pos["y"]:.2f}), edge constraint automatically satisfied',
                'required_distance': required_distance,
                'actual_distance': required_distance,  # 视为满足
                'in_reagent_cabinet': True
            }
        
        # 获取工作表面边界
        work_surface = obj['initial_location']
        bounds = self._get_surface_bounds(layout, work_surface)
        
        if bounds is None:
            return 1.0, {'expected': '', 'actual': 'Unable to get work surface bounds'}
        
        # 计算到边缘的距离
        bbox = self.asset_loader.get_asset_bbox(obj['id'])
        pos = obj['position']
        rotation = obj['rotation']['z']
        
        actual_distance, nearest_edge = calculate_edge_distance(pos, bbox, rotation, bounds)
        
        # 计算满足度
        ratio = actual_distance / required_distance
        satisfaction = calculate_satisfaction(ratio)
        
        return satisfaction, {
            'expected': f'{asset} distance from edge ≥ {required_distance}cm',
            'actual': f'{nearest_edge} edge {actual_distance:.1f}cm',
            'required_distance': required_distance,
            'actual_distance': actual_distance,
            'nearest_edge': nearest_edge,
            'ratio': ratio
        }
    
    def _evaluate_zone_constraint(self, layout: Dict, constraint: Dict,
                                  config: Dict) -> tuple[float, Dict]:
        """
        评估功能分区约束（C10）
        
        Args:
            layout: 布局JSON
            constraint: 约束定义
            config: 约束配置
        
        Returns:
            (satisfaction, details)
        """
        asset = constraint.get('asset1')
        required_zone = config.get('required_zone', 'experimental')
        
        # 查找物体
        obj = self._find_object(layout, asset)
        if obj is None:
            return 0.0, {
                'expected': f'{asset} should be in {required_zone} zone',
                'actual': f'Object not found (missing: {asset}), cannot satisfy constraint'
            }
        
        # 获取工作表面边界
        work_surface = obj['initial_location']
        bounds = self._get_surface_bounds(layout, work_surface)
        
        if bounds is None:
            return 1.0, {'expected': '', 'actual': 'Unable to get work surface bounds'}
        
        # 计算位置比例（0=前，1=后）
        pos = obj['position']
        position_ratio = calculate_position_ratio(pos, bounds, axis='y')
        
        # 判断所在分区
        from labtouchstone.evaluator.config import FUNCTIONAL_ZONES
        actual_zone = None
        for zone_name, (min_ratio, max_ratio) in FUNCTIONAL_ZONES.items():
            if min_ratio <= position_ratio <= max_ratio:
                actual_zone = zone_name
                break
        
        # 判断是否在正确分区
        if actual_zone == required_zone:
            satisfaction = 1.0
        else:
            satisfaction = 0.0
        
        return satisfaction, {
            'expected': f'{asset} should be in {required_zone} zone',
            'actual': f'{asset} is in {actual_zone} zone (position ratio {position_ratio:.2f})',
            'required_zone': required_zone,
            'actual_zone': actual_zone,
            'position_ratio': position_ratio
        }
    
    def _find_object(self, layout: Dict, asset_name: str) -> Dict:
        """查找物体"""
        for obj in layout['objects']:
            asset_id = obj['id']
            
            # 排除房间本身
            if asset_id == 'LaboratoryRoom':
                continue
            
            # 匹配资产名称（asset_name可能只是类别名，如"Ethanol"）
            if asset_name in asset_id or asset_id.startswith(asset_name):
                return obj
        return None
    
    def _find_object_position(self, layout: Dict, asset_name: str) -> Dict:
        """查找物体位置"""
        obj = self._find_object(layout, asset_name)
        return obj['position'] if obj else None
    
    def _find_object_work_surface(self, layout: Dict, asset_name: str) -> str:
        """查找物体所在的工作表面"""
        obj = self._find_object(layout, asset_name)
        return obj['initial_location'] if obj else None
    
    def _get_surface_bounds(self, layout: Dict, surface_name: str) -> Dict[str, float]:
        """获取工作表面的边界
        
        Args:
            layout: 布局JSON
            surface_name: 工作表面的资产ID（如'LabBench', 'FumeHood', 'ValidationPlatform'等）
        
        Returns:
            bounds: {'x_min', 'x_max', 'y_min', 'y_max'}
        """
        # 使用公共函数避免代码重复
        from labtouchstone.evaluator.utils.geometry import get_surface_bounds
        return get_surface_bounds(layout, surface_name, self.asset_loader)
    
    def _is_inside_reagent_cabinet_bbox(self, layout: Dict, obj: Dict) -> bool:
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
    
