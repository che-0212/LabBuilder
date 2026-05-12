"""
物理评估器
整合物理约束和化学约束检查，提供完整的物理评估（70分）
"""

from typing import Dict
from labtouchstone.evaluator.physical_constraint_checker import PhysicalConstraintChecker
from labtouchstone.evaluator.chemical_constraint_checker import ChemicalConstraintChecker
from labtouchstone.evaluator.utils.asset_loader import AssetLoader


class PhysicalEvaluator:
    """
    物理评估器
    
    评分结构：
    - 物理约束（35分）：边界、碰撞、高度
    - 化学约束（35分，动态分配）：C1-C10约束
    """
    
    def __init__(self, asset_db_path: str):
        """
        初始化物理评估器
        
        Args:
            asset_db_path: Asset.json文件路径
        """
        self.asset_loader = AssetLoader(asset_db_path)
        self.physical_checker = PhysicalConstraintChecker(self.asset_loader)
        self.chemical_checker = ChemicalConstraintChecker(self.asset_loader)
        self.max_physical_score = 35
        self.max_chemical_score = 35
    
    def evaluate(self, layout: Dict, protocol: Dict) -> Dict:
        """
        评估布局的物理约束和化学安全约束
        
        Args:
            layout: 布局JSON数据
            protocol: 实验协议JSON数据
        
        Returns:
            result: 包含总分、各项得分、违规列表的字典
        """
        result = {
            'total_score': 0,
            'max_score': 70,  # 修改为70分
            'physical_constraints': {},
            'chemical_constraints': {},
            'violations': [],
            'summary': {}
        }
        
        # 1. 物理约束检查（35分固定）
        print("正在检查物理约束...")
        physical_result = self.physical_checker.check_all(layout, protocol)
        result['physical_constraints'] = physical_result
        result['violations'].extend(physical_result['violations'])
        
        # 2. 化学安全约束检查（35分动态）
        print("正在检查化学安全约束...")
        chemical_result = self.chemical_checker.check_all(layout, protocol)
        result['chemical_constraints'] = chemical_result
        result['violations'].extend(chemical_result['violations'])
        
        # 3. 计算总分
        result['total_score'] = (
            physical_result['score'] + 
            chemical_result['score']
        )
        
        # 4. 生成摘要
        result['summary'] = self._generate_summary(physical_result, chemical_result)
        
        return result
    
    def _generate_summary(self, physical_result: Dict, chemical_result: Dict) -> Dict:
        """
        生成评估摘要
        
        Args:
            physical_result: 物理约束检查结果
            chemical_result: 化学约束检查结果
        
        Returns:
            summary: 摘要信息
        """
        total_score = physical_result['score'] + chemical_result['score']
        
        # 统计违规
        physical_violations = physical_result['violations']
        chemical_violations = chemical_result['violations']
        total_violations = len(physical_violations) + len(chemical_violations)
        
        # 统计严重违规
        critical_violations = sum(
            1 for v in physical_violations + chemical_violations
            if v.get('severity') == 'high' or 
               (v.get('constraint') in chemical_violations and v.get('satisfaction', 1.0) < 0.5)
        )
        
        # 判断是否通过
        passed = total_score >= 56  # 80%及格线
        
        return {
            'physical_score': f"{physical_result['score']:.1f}/35",
            'chemical_score': f"{chemical_result['score']:.1f}/35",
            'total_score': f"{total_score:.1f}/70",
            'percentage': f"{total_score/70*100:.1f}%",
            'total_violations': total_violations,
            'critical_violations': critical_violations,
            'passed': passed,
            'grade': self._get_grade(total_score / 70 * 100)
        }
    
    def _get_grade(self, percentage: float) -> str:
        """根据百分比获取等级"""
        if percentage >= 90:
            return 'A'
        elif percentage >= 80:
            return 'B'
        elif percentage >= 70:
            return 'C'
        elif percentage >= 60:
            return 'D'
        else:
            return 'F'

