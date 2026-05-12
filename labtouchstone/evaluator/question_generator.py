"""
问题生成器
根据实验协议动态生成10个评估问题
"""

from typing import Dict, List


class QuestionGenerator:
    """语义评估问题生成器"""
    
    def __init__(self):
        """初始化问题生成器"""
        self.question_templates = self._load_templates()
    
    def generate_questions(self, protocol: Dict) -> List[Dict]:
        """
        根据协议生成5个问题
        
        Args:
            protocol: 实验协议JSON
        
        Returns:
            questions: 问题列表
        """
        questions = []
        
        # 1. 添加固定的空间布局问题（1题）
        questions.extend(self._generate_layout_questions(protocol)[:1])
        
        # 2. 基于化学约束生成安全性问题（2题）
        if len(questions) < 5:
            questions.extend(self._generate_safety_questions(protocol)[:2])
        
        # 3. 基于实验步骤生成工作流问题（1题）
        if len(questions) < 5:
            questions.extend(self._generate_workflow_questions(protocol)[:1])
        
        # 4. 补充美观性问题（1题）
        if len(questions) < 5:
            questions.extend(self._generate_aesthetics_questions(protocol)[:1])
        
        # 5. 截取前5题并分配ID
        questions = questions[:5]
        for i, q in enumerate(questions):
            q['id'] = i + 1
            q['max_score'] = 6  # 改为每题6分，总共30分
        
        return questions
    
    def _generate_layout_questions(self, protocol: Dict) -> List[Dict]:
        """生成空间布局问题（固定2题）"""
        experiment_name = protocol.get('experiment_name', '本实验')
        
        return [
            {
                'category': 'layout',
                'question': f"From the top view (top_view), is the overall laboratory layout reasonable? Please evaluate:\n1) Are work surfaces (lab benches, fume hoods) utilized adequately?\n2) Is there a clear functional zoning of items?\n3) Is sufficient space reserved for {experiment_name} operations?",
                'views': ['top_view'],
                'assets': []
            },
            {
                'category': 'layout',
                'question': "From the operator's perspective (front_view), are the items on the lab bench easy to operate? Please evaluate:\n1) Accessibility of frequently used items\n2) Whether there is any visual obstruction\n3) Whether the operating space is sufficient",
                'views': ['front_view'],
                'assets': []
            }
        ]
    
    def _generate_safety_questions(self, protocol: Dict) -> List[Dict]:
        """生成安全性问题（基于化学约束）"""
        questions = []
        constraints = protocol.get('chemical_constraints', [])
        
        for constraint in constraints:
            ctype = constraint.get('constraint_type')
            
            if ctype == 'C1':
                # 易燃物与热源分离
                asset1 = constraint.get('asset1')
                asset2 = constraint.get('asset2')
                questions.append({
                    'category': 'safety',
                    'question': f"From the top view (top_view) and front view (front_view), is the positional relationship between {asset1} (flammable material) and {asset2} (heat source) safe?\nPlease assess:\n1) Is the distance between them sufficiently far (should be ≥100cm)?\n2) Are there any obstructing items or items too close?\n3) From a safety perspective, does this layout pose any hazards?",
                    'views': ['top_view', 'front_view'],
                    'assets': [asset1, asset2],
                    'constraint': 'C1'
                })
            
            elif ctype == 'C3':
                # 通风橱约束
                asset1 = constraint.get('asset1')
                questions.append({
                    'category': 'safety',
                    'question': f"From the fume hood view (fume_hood_view) and top view (top_view), is {asset1} (volatile/toxic reagent) correctly placed inside the fume hood?\nPlease assess:\n1) Is the reagent within the fume hood area?\n2) Is the position convenient for ventilation and operation?\n3) Does it comply with chemical laboratory safety regulations?",
                    'views': ['fume_hood_view', 'top_view'],
                    'assets': [asset1],
                    'constraint': 'C3'
                })
            
            elif ctype == 'C6':
                # 酸碱分离
                asset1 = constraint.get('asset1')
                asset2 = constraint.get('asset2')
                questions.append({
                    'category': 'safety',
                    'question': f"From the top view (top_view), is the placement of {asset1} (acid) and {asset2} (base) safe?\nPlease assess:\n1) Is the distance between them sufficient (should be ≥50cm)?\n2) Are they stored in different areas?\n3) In case of accidental spillage, is there sufficient safety distance?",
                    'views': ['top_view', 'front_view'],
                    'assets': [asset1, asset2],
                    'constraint': 'C6'
                })
            
            # 限制安全问题数量
            if len(questions) >= 4:
                break
        
        # 如果没有足够的安全问题，添加通用安全问题
        if len(questions) < 3:
            questions.append({
                'category': 'safety',
                'question': "From all views, are there any obvious safety hazards in the layout?\nPlease check:\n1) Are any items too close to the edge (risk of falling)?\n2) Are fragile items stacked or placed unstably?\n3) In an emergency, can operators evacuate quickly?",
                'views': ['top_view', 'front_view', 'left_view', 'right_view'],
                'assets': []
            })
        
        return questions
    
    def _generate_workflow_questions(self, protocol: Dict) -> List[Dict]:
        """生成工作流问题（基于实验步骤）"""
        questions = []
        procedures = protocol.get('procedure', [])
        
        if len(procedures) == 0:
            return questions
        
        # 选取前3个关键步骤
        key_steps = procedures[:3]
        
        for step in key_steps:
            step_num = step.get('step_number', 0)
            description = step.get('description', '')
            assets = step.get('assets_involved', [])
            
            if len(assets) > 0:
                assets_str = '、'.join(assets)
                questions.append({
                    'category': 'workflow',
                    'question': f"Experimental Step {step_num}: {description}\nItems involved: {assets_str}\n\nFrom the front view (front_view) and top view (top_view), are these items positioned conveniently for executing this step?\nPlease evaluate:\n1) Are items within a reasonable operating range?\n2) Is sequential operation smooth?\n3) Is significant movement or transportation required?",
                    'views': ['front_view', 'top_view'],
                    'assets': assets,
                    'step': step_num
                })
            
            # 限制工作流问题数量
            if len(questions) >= 3:
                break
        
        # 如果步骤较少，添加通用工作流问题
        if len(questions) < 2:
            all_assets = protocol.get('assets', [])
            asset_names = [asset.get('name') for asset in all_assets[:5]]
            if asset_names:
                assets_str = '、'.join(asset_names)
                questions.append({
                    'category': 'workflow',
                    'question': f"From the overall layout perspective, do the relative positions of main experimental items ({assets_str}, etc.) support a smooth experimental workflow?\nPlease evaluate:\n1) Are items arranged for sequential use?\n2) Is unnecessary back-and-forth movement avoided?\n3) Is the overall workflow path reasonable?",
                    'views': ['top_view', 'front_view'],
                    'assets': asset_names
                })
        
        return questions
    
    def _generate_aesthetics_questions(self, protocol: Dict) -> List[Dict]:
        """生成美观性问题（1题）"""
        return [
            {
                'category': 'aesthetics',
                'question': "From all views, does the overall layout reflect the professionalism and standardization expected of a chemical laboratory?\nPlease evaluate:\n1) Is the layout neat and orderly?\n2) Are similar items (e.g., reagent bottles, glassware) reasonably grouped or aligned?\n3) Is the overall visual effect professional?\n4) Does it conform to standard chemical laboratory layout practices?",
                'views': ['top_view', 'front_view'],
                'assets': []
            }
        ]
    
    def _load_templates(self) -> Dict:
        """加载问题模板（预留扩展）"""
        return {}

