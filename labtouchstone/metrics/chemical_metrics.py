"""
化学指标计算器
计算布局的化学安全指标：将10个化学约束归类为4类并计算满足度
"""

import os
import sys
from typing import Dict, List

# 添加父目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from labtouchstone.evaluator.chemical_constraint_checker import ChemicalConstraintChecker
from labtouchstone.evaluator.utils.asset_loader import AssetLoader


class ChemicalMetrics:
    """化学指标计算器"""
    
    # 化学约束分类映射
    # 类别1：易燃试剂与热源分离
    CATEGORY_1_FLAMMABLE_HEAT = ['C1']
    
    # 类别2：试剂放在试剂柜
    CATEGORY_2_REAGENT_STORAGE = ['C2', 'C3']
    
    # 类别3：不相容试剂分离
    CATEGORY_3_INCOMPATIBLE_SEPARATION = ['C5', 'C6', 'C7', 'C8', 'C9']
    
    # 类别4：玻璃仪器远离边缘
    CATEGORY_4_GLASS_EDGE = ['C4']
    
    # 所有约束类型到类别的映射
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
        'C10': None  # C10不在4类中，但保留用于完整性
    }
    
    def __init__(self, asset_db_path: str):
        """
        初始化化学指标计算器
        
        Args:
            asset_db_path: assets_annotated.json文件路径
        """
        asset_loader = AssetLoader(asset_db_path)
        self.checker = ChemicalConstraintChecker(asset_loader)
    
    def calculate_all(self, layout: Dict, protocol: Dict) -> Dict:
        """
        计算所有化学指标
        
        Args:
            layout: 布局JSON数据
            protocol: 实验协议JSON数据（包含chemical_constraints或llm_generated_constraints）
        
        Returns:
            metrics: 包含所有化学指标的字典
        """
        # 获取协议中的化学约束（优先使用LLM生成的约束）
        llm_constraints = protocol.get('llm_generated_constraints', [])
        standard_constraints = protocol.get('chemical_constraints', [])
        
        # 如果有LLM约束，使用简化的计算方式
        if llm_constraints:
            return self._calculate_llm_constraints(layout, protocol, llm_constraints)
        
        # 使用标准约束的原有逻辑
        constraints = standard_constraints
        
        if len(constraints) == 0:
            return {
                'total_constraints': 0,
                'category_metrics': {
                    'flammable_heat_separation': {
                        'category_name': '易燃试剂与热源分离',
                        'constraint_count': 0,
                        'satisfaction': 1.0,  # 无约束=完美满足
                        'constraints': []
                    },
                    'reagent_storage': {
                        'category_name': '试剂放在试剂柜',
                        'constraint_count': 0,
                        'satisfaction': 1.0,
                        'constraints': []
                    },
                    'incompatible_separation': {
                        'category_name': '不相容试剂分离',
                        'constraint_count': 0,
                        'satisfaction': 1.0,
                        'constraints': []
                    },
                    'glass_edge_avoidance': {
                        'category_name': '玻璃仪器远离边缘',
                        'constraint_count': 0,
                        'satisfaction': 1.0,
                        'constraints': []
                    }
                },
                'overall_satisfaction': 1.0,  # 无约束=完美满足
                'check_result': {
                    'score': 0,
                    'max_score': 0,
                    'violations_count': 0
                },
                'note': '本实验无化学安全约束'
            }
        
        # 使用评估器的检查器计算每个约束的满足度
        check_result = self.checker.check_all(layout, protocol)
        
        # 按类别分组约束
        category_constraints = {
            'flammable_heat_separation': [],
            'reagent_storage': [],
            'incompatible_separation': [],
            'glass_edge_avoidance': []
        }
        
        # 将约束结果按类别分组
        for constraint_result in check_result.get('constraint_results', []):
            constraint_type = constraint_result['constraint_type']
            category = self.CONSTRAINT_TO_CATEGORY.get(constraint_type)
            
            if category and category in category_constraints:
                category_constraints[category].append(constraint_result)
        
        # 计算每个类别的指标
        category_metrics = {}
        
        for category_key, category_name in [
            ('flammable_heat_separation', '易燃试剂与热源分离'),
            ('reagent_storage', '试剂放在试剂柜'),
            ('incompatible_separation', '不相容试剂分离'),
            ('glass_edge_avoidance', '玻璃仪器远离边缘')
        ]:
            constraints_in_category = category_constraints[category_key]
            
            if len(constraints_in_category) == 0:
                category_metrics[category_key] = {
                    'category_name': category_name,
                    'constraint_count': 0,
                    'satisfaction': 1.0,  # 无约束=完美满足
                    'constraints': []
                }
            else:
                # 计算该类别的平均满足度
                satisfactions = [c['satisfaction'] for c in constraints_in_category]
                avg_satisfaction = sum(satisfactions) / len(satisfactions)
                
                # 统计通过和未通过的约束
                passed_count = sum(1 for c in constraints_in_category if c.get('passed', False))
                
                category_metrics[category_key] = {
                    'category_name': category_name,
                    'constraint_count': len(constraints_in_category),
                    'passed_count': passed_count,
                    'failed_count': len(constraints_in_category) - passed_count,
                    'satisfaction': avg_satisfaction,
                    'constraints': [
                        {
                            'constraint_type': c['constraint_type'],
                            'description': c.get('description', ''),
                            'satisfaction': c['satisfaction'],
                            'passed': c.get('passed', False),
                            'details': c.get('details', {})
                        }
                        for c in constraints_in_category
                    ]
                }
        
        return {
            'total_constraints': len(constraints),
            'category_metrics': category_metrics,
            'overall_satisfaction': check_result.get('score', 0) / check_result.get('max_score', 35) if check_result.get('max_score', 35) > 0 else 1.0,
            'check_result': {
                'score': check_result.get('score', 0),
                'max_score': check_result.get('max_score', 35),
                'violations_count': len(check_result.get('violations', []))
            }
        }
    
    def _calculate_llm_constraints(self, layout: Dict, protocol: Dict, llm_constraints: List[Dict]) -> Dict:
        """
        计算LLM生成约束的指标（不按C1-C10分类，直接返回所有约束的满足度）
        """
        # 使用checker计算约束满足度
        check_result = self.checker.check_all(layout, protocol)
        
        # 不再按C1-C10分类，直接返回结果
        # 为了兼容性，创建一个简化的category_metrics
        total_constraints = len(llm_constraints)
        if total_constraints == 0:
            avg_satisfaction = 1.0
        else:
            # 计算平均满足度
            constraint_results = check_result.get('constraint_results', [])
            if constraint_results:
                avg_satisfaction = sum(c.get('satisfaction', 0) for c in constraint_results) / len(constraint_results)
            else:
                avg_satisfaction = 0.0
        
        # 创建兼容的category_metrics（所有约束放在一个虚拟类别中）
        category_metrics = {
            'llm_generated': {
                'category_name': 'LLM生成的安全约束',
                'constraint_count': total_constraints,
                'satisfaction': avg_satisfaction,
                'constraints': check_result.get('constraint_results', [])
            },
            # 为了兼容batch_chemical_metrics，添加空的标准类别
            'flammable_heat_separation': {'category_name': '易燃试剂与热源分离', 'constraint_count': 0, 'satisfaction': 1.0, 'constraints': []},
            'reagent_storage': {'category_name': '试剂放在试剂柜', 'constraint_count': 0, 'satisfaction': 1.0, 'constraints': []},
            'incompatible_separation': {'category_name': '不相容试剂分离', 'constraint_count': 0, 'satisfaction': 1.0, 'constraints': []},
            'glass_edge_avoidance': {'category_name': '玻璃仪器远离边缘', 'constraint_count': 0, 'satisfaction': 1.0, 'constraints': []}
        }
        
        # 计算overall_satisfaction
        score = check_result.get('score', 0)
        max_score = check_result.get('max_score', 1)
        overall_satisfaction = score / max_score if max_score > 0 else 1.0
        
        return {
            'total_constraints': total_constraints,
            'category_metrics': category_metrics,
            'overall_satisfaction': overall_satisfaction,
            'check_result': {
                'score': score,
                'max_score': max_score,
                'violations_count': len(check_result.get('violations', []))
            },
            'note': f'使用LLM生成的{total_constraints}个安全约束'
        }
    
    def calculate_category_summary(self, layout: Dict, protocol: Dict) -> Dict:
        """
        计算简化的类别汇总指标（仅返回4个类别的满足度）
        
        Args:
            layout: 布局JSON数据
            protocol: 实验协议JSON数据
        
        Returns:
            summary: 包含4个类别满足度的简化字典
        """
        full_metrics = self.calculate_all(layout, protocol)
        
        summary = {
            'flammable_heat_separation': full_metrics['category_metrics']['flammable_heat_separation']['satisfaction'],
            'reagent_storage': full_metrics['category_metrics']['reagent_storage']['satisfaction'],
            'incompatible_separation': full_metrics['category_metrics']['incompatible_separation']['satisfaction'],
            'glass_edge_avoidance': full_metrics['category_metrics']['glass_edge_avoidance']['satisfaction']
        }
        
        return summary
    
    def calculate_dual_evaluation(self, layout: Dict, protocol: Dict) -> Dict:
        """
        双重标准评估：同时评估LLM约束和标准规则
        
        用于论文实验：展示LLM生成的约束vs标准安全规则的对比
        
        Args:
            layout: 布局JSON数据
            protocol: 实验协议JSON数据（应包含llm_generated_constraints）
        
        Returns:
            双重评估结果，包含：
            - LLM约束满足度
            - 标准规则满足度（C1-C10）
            - 约束覆盖率分析
        """
        result = {
            'llm_constraints': None,
            'standard_rules': None,
            'coverage_analysis': None,
            'note': ''
        }
        
        # 1. 评估LLM生成的约束
        llm_constraints = protocol.get('llm_generated_constraints', [])
        if llm_constraints:
            # 临时创建一个只有LLM约束的protocol
            temp_protocol_llm = {**protocol, 'chemical_constraints': []}
            llm_result = self.checker.check_all(layout, temp_protocol_llm)
            
            result['llm_constraints'] = {
                'total': len(llm_constraints),
                'score': llm_result.get('score', 0),
                'max_score': llm_result.get('max_score', 0),
                'satisfaction': llm_result.get('score', 0) / llm_result.get('max_score', 1) if llm_result.get('max_score', 0) > 0 else 0,
                'violations_count': len(llm_result.get('violations', [])),
                'constraint_results': llm_result.get('constraint_results', [])
            }
        else:
            result['note'] = 'No LLM-generated constraints found'
        
        # 2. 评估标准规则（构造C1-C10约束）
        # 这里需要根据实验中的资产自动生成标准规则进行评估
        # 为简化实现，先标记为未实现
        result['standard_rules'] = {
            'note': 'Standard rules evaluation not implemented yet. Would require mapping assets to C1-C10 constraints.'
        }
        
        # 3. 覆盖率分析
        if llm_constraints:
            coverage = self._analyze_constraint_coverage(llm_constraints)
            result['coverage_analysis'] = coverage
        
        return result
    
    def _analyze_constraint_coverage(self, llm_constraints: List[Dict]) -> Dict:
        """
        分析LLM约束覆盖了哪些标准规则类别
        
        Args:
            llm_constraints: LLM生成的约束列表
        
        Returns:
            覆盖率分析结果
        """
        # 标准规则类别
        standard_categories = {
            'flammable_heat_separation': ['flammable', 'heat', 'ignition'],
            'reagent_storage': ['storage', 'cabinet', 'reagent'],
            'incompatible_separation': ['incompatible', 'reactive', 'separate'],
            'glass_edge_avoidance': ['glass', 'edge', 'breakage'],
            'acid_base_separation': ['acid', 'base'],
            'oxidizer_organic': ['oxidizer', 'organic'],
            'metal_acid': ['metal', 'acid'],
        }
        
        coverage = {
            'covered_categories': [],
            'uncovered_categories': [],
            'coverage_details': {}
        }
        
        # 检查每个标准类别是否被LLM约束覆盖
        for category, keywords in standard_categories.items():
            is_covered = False
            matching_constraints = []
            
            for constraint in llm_constraints:
                constraint_type = constraint.get('constraint_type', '').lower()
                description = constraint.get('description', '').lower()
                reason = constraint.get('reason', '').lower()
                
                # 检查是否包含关键词
                text = f"{constraint_type} {description} {reason}"
                if any(keyword in text for keyword in keywords):
                    is_covered = True
                    matching_constraints.append(constraint.get('constraint_type'))
            
            if is_covered:
                coverage['covered_categories'].append(category)
                coverage['coverage_details'][category] = {
                    'covered': True,
                    'matching_constraints': matching_constraints
                }
            else:
                coverage['uncovered_categories'].append(category)
                coverage['coverage_details'][category] = {
                    'covered': False
                }
        
        # 计算覆盖率
        total_categories = len(standard_categories)
        covered_count = len(coverage['covered_categories'])
        coverage['coverage_rate'] = covered_count / total_categories if total_categories > 0 else 0
        coverage['coverage_percentage'] = f"{coverage['coverage_rate'] * 100:.1f}%"
        
        return coverage

