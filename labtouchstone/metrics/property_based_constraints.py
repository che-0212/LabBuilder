"""
基于属性的化学约束生成器

根据布局中资产的化学属性自动生成所有可能的约束组合，
而不是依赖protocol中预定义的约束。

这样可以：
1. 更全面地评估化学安全
2. 不会遗漏任何潜在危险组合
3. 初始布局更容易违反约束（约束数量更多）
"""

import os
import sys
from typing import Dict, List, Tuple, Set
from itertools import product

# 添加父目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from labtouchstone.evaluator.utils.asset_loader import AssetLoader


class PropertyBasedConstraintGenerator:
    """基于属性的约束生成器"""
    
    # 约束规则定义
    # 四个化学metric类别：
    # 1. 易燃试剂与热源分离 (C1)
    # 2. 试剂放在试剂柜 (C3) - 所有试剂类型资产
    # 3. 不相容试剂分离 (C5-C9)
    # 4. 玻璃仪器远离边缘 (C4)
    
    CONSTRAINT_RULES = {
        # 类别1：易燃试剂与热源分离
        'C1': {
            'name': 'flammable_heat_separation',
            'prop1': 'flammable',
            'prop2': 'heat_source',
            'threshold': 150,  # cm (1.5m)
            'description': '易燃物与热源分离',
            'weight': 5,
            'type': 'distance'
        },
        # 类别2：试剂放在试剂柜
        'C3': {
            'name': 'reagent_cabinet_storage',
            'prop1': 'is_reagent',  # 特殊属性：通过type=reagent判断
            'prop2': None,
            'threshold': None,
            'description': '试剂存放在试剂柜',
            'weight': 5,
            'type': 'location',
            'required_location': 'reagent_cabinet'
        },
        # 类别3：不相容试剂分离
        'C5': {
            'name': 'flammable_oxidizer_separation',
            'prop1': 'flammable',
            'prop2': 'oxidizer',
            'threshold': 150,  # cm (1.5m)
            'description': '易燃物与氧化剂分离',
            'weight': 4,
            'type': 'distance'
        },
        'C6': {
            'name': 'acid_base_separation',
            'prop1': 'acid',
            'prop2': 'base',
            'threshold': 150,  # cm (1.5m)
            'description': '酸碱分离',
            'weight': 4,
            'type': 'distance'
        },
        'C7': {
            'name': 'oxidizer_organic_separation',
            'prop1': 'oxidizer',
            'prop2': 'flammable',  # organic solvents are usually flammable
            'threshold': 150,  # cm (1.5m)
            'description': '氧化剂与有机物分离',
            'weight': 3,
            'type': 'distance'
        },
        'C8': {
            'name': 'metal_acid_separation',
            'prop1': 'reactive_metal',
            'prop2': 'acid',
            'threshold': 150,  # cm (1.5m)
            'description': '活性金属与酸分离',
            'weight': 2,
            'type': 'distance'
        },
        # 类别4：玻璃仪器远离边缘
        'C4': {
            'name': 'glass_edge_avoidance',
            'prop1': 'glass_container',
            'prop2': None,
            'threshold': 30,  # cm from edge
            'description': '玻璃容器远离边缘',
            'weight': 3,
            'type': 'edge_distance'
        },
    }
    
    def __init__(self, asset_loader: AssetLoader):
        """
        初始化约束生成器
        
        Args:
            asset_loader: 资产加载器实例
        """
        self.asset_loader = asset_loader
        self.asset_db = asset_loader.asset_db
    
    def get_asset_props(self, asset_id: str) -> Dict:
        """
        获取资产的化学属性
        
        Args:
            asset_id: 资产ID（可能包含后缀如 Acetone_001）
        
        Returns:
            props字典，如 {'flammable': True, 'acid': False, ...}
        """
        # 尝试直接匹配
        asset_info = self.asset_loader.get_asset_info(asset_id)
        if asset_info and 'props' in asset_info:
            return asset_info['props']
        
        # 尝试去掉后缀匹配（如 Acetone_001 -> Acetone）
        base_id = asset_id.rsplit('_', 1)[0] if '_' in asset_id else asset_id
        asset_info = self.asset_loader.get_asset_info(base_id)
        if asset_info and 'props' in asset_info:
            return asset_info['props']
        
        # 返回默认属性（全为False）
        return {
            'flammable': False,
            'explosive': False,
            'volatile_or_toxic': False,
            'glass_container': False,
            'heat_source': False,
            'acid': False,
            'base': False,
            'oxidizer': False,
            'reactive_metal': False
        }
    
    def generate_constraints_from_layout(self, layout: Dict) -> List[Dict]:
        """
        根据布局中的资产属性自动生成所有约束
        
        Args:
            layout: 布局JSON数据
        
        Returns:
            constraints: 生成的约束列表
        """
        # 1. 收集布局中所有资产及其属性
        assets_by_prop = self._classify_assets_by_property(layout)
        
        # 2. 生成所有约束
        constraints = []
        
        for constraint_type, rule in self.CONSTRAINT_RULES.items():
            prop1 = rule['prop1']
            prop2 = rule['prop2']
            rule_type = rule.get('type', 'distance')
            
            if rule_type == 'location':
                # 位置约束（C3试剂存储）
                for asset in assets_by_prop.get(prop1, []):
                    constraints.append({
                        'constraint_type': constraint_type,
                        'description': f"{rule['description']}: {asset}",
                        'asset1': asset,
                        'asset2': None,
                        'threshold': None,
                        'required_location': rule.get('required_location'),
                        'weight': rule['weight'],
                        'rule_type': 'location'
                    })
            elif prop2 is None:
                # 单一属性约束（如C4玻璃器皿边缘约束）
                for asset in assets_by_prop.get(prop1, []):
                    constraints.append({
                        'constraint_type': constraint_type,
                        'description': f"{rule['description']}: {asset}",
                        'asset1': asset,
                        'asset2': None,
                        'threshold': rule['threshold'],
                        'weight': rule['weight'],
                        'rule_type': 'edge_distance'
                    })
            else:
                # 双属性约束（如C1易燃物与热源）
                assets1 = assets_by_prop.get(prop1, [])
                assets2 = assets_by_prop.get(prop2, [])
                
                # 生成所有组合
                for asset1, asset2 in product(assets1, assets2):
                    if asset1 != asset2:  # 不能是同一个资产
                        constraints.append({
                            'constraint_type': constraint_type,
                            'description': f"{rule['description']}: {asset1} ↔ {asset2}",
                            'asset1': asset1,
                            'asset2': asset2,
                            'threshold': rule['threshold'],
                            'weight': rule['weight'],
                            'rule_type': 'distance'
                        })
        
        return constraints
    
    def _classify_assets_by_property(self, layout: Dict) -> Dict[str, List[str]]:
        """
        将布局中的资产按化学属性分类
        
        Args:
            layout: 布局JSON
        
        Returns:
            按属性分类的资产字典，如 {'flammable': ['Acetone', 'Ethanol'], ...}
        """
        result = {
            'flammable': [],
            'explosive': [],
            'volatile_or_toxic': [],
            'glass_container': [],
            'heat_source': [],
            'acid': [],
            'base': [],
            'oxidizer': [],
            'reactive_metal': [],
            'is_reagent': []  # 特殊属性：所有试剂类型的资产
        }
        
        for obj in layout.get('objects', []):
            asset_id = obj.get('id', '')
            
            # 跳过房间本身
            if asset_id == 'LaboratoryRoom':
                continue
            
            # 获取属性
            props = self.get_asset_props(asset_id)
            
            # 分类
            for prop_name, prop_value in props.items():
                if prop_value and prop_name in result:
                    result[prop_name].append(asset_id)
            
            # 检查是否为试剂（通过type判断）
            if self._is_reagent_type(asset_id):
                result['is_reagent'].append(asset_id)
        
        return result
    
    def _is_reagent_type(self, asset_id: str) -> bool:
        """
        判断资产是否为试剂类型
        
        Args:
            asset_id: 资产ID
        
        Returns:
            True if the asset is a reagent
        """
        # 尝试直接匹配
        asset_info = self.asset_loader.get_asset_info(asset_id)
        if asset_info and asset_info.get('type') == 'reagent':
            return True
        
        # 尝试去掉后缀匹配
        base_id = asset_id.rsplit('_', 1)[0] if '_' in asset_id else asset_id
        asset_info = self.asset_loader.get_asset_info(base_id)
        if asset_info and asset_info.get('type') == 'reagent':
            return True
        
        return False
    
    def get_constraint_summary(self, constraints: List[Dict]) -> Dict:
        """
        生成约束统计摘要
        
        Args:
            constraints: 约束列表
        
        Returns:
            摘要字典
        """
        summary = {
            'total': len(constraints),
            'by_type': {}
        }
        
        for c in constraints:
            ctype = c['constraint_type']
            if ctype not in summary['by_type']:
                summary['by_type'][ctype] = {
                    'count': 0,
                    'description': self.CONSTRAINT_RULES.get(ctype, {}).get('description', ''),
                    'pairs': []
                }
            summary['by_type'][ctype]['count'] += 1
            if c.get('asset2'):
                summary['by_type'][ctype]['pairs'].append(f"{c['asset1']} ↔ {c['asset2']}")
            else:
                summary['by_type'][ctype]['pairs'].append(c['asset1'])
        
        return summary


def test_generator():
    """测试约束生成器"""
    import json
    
    # 加载资产数据库
    asset_loader = AssetLoader('assets_annotated.json')
    generator = PropertyBasedConstraintGenerator(asset_loader)
    
    # 加载一个布局文件测试
    layout_path = 'OUTPUT/gemini-3-flash-preview_layout/Alkylation_Reaction_using_Sodium_Hydride_20260117_201153/Alkylation_Reaction_using_Sodium_Hydride_room_isaacsim.json'
    
    with open(layout_path, 'r') as f:
        layout = json.load(f)
    
    # 生成约束
    constraints = generator.generate_constraints_from_layout(layout)
    
    # 打印摘要
    summary = generator.get_constraint_summary(constraints)
    print(f"\n=== 自动生成的约束 ===")
    print(f"总约束数: {summary['total']}")
    print()
    
    for ctype, info in summary['by_type'].items():
        print(f"{ctype} ({info['description']}): {info['count']}个")
        for pair in info['pairs'][:3]:
            print(f"  - {pair}")
        if len(info['pairs']) > 3:
            print(f"  ... 还有 {len(info['pairs'])-3} 个")
        print()


if __name__ == '__main__':
    test_generator()

