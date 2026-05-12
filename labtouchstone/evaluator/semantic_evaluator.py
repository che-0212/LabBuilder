"""
语义评估器
使用LLM对渲染图片进行语义评分（30分）
"""

import json
import time
from typing import Dict, List, Optional
from labtouchstone.evaluator.question_generator import QuestionGenerator
from labtouchstone.evaluator.utils.file_utils import find_experiment_images, load_image_as_base64
from labtouchstone.evaluator.config import LLM_CONFIG, IMAGE_CONFIG
from utils.llm_config import LLMConfig, ModelAPI


class SemanticEvaluator:
    """
    语义评估器
    
    使用LLM分析渲染图片，评估布局的合理性、安全性、工作流等方面
    """
    
    def __init__(self, llm_config: Optional[Dict] = None):
        """
        初始化语义评估器
        
        Args:
            llm_config: LLM配置（可选，使用默认配置）
        """
        self.question_generator = QuestionGenerator()
        
        # 初始化LLM
        config = llm_config or LLM_CONFIG
        self.llm_config = LLMConfig(**config)
        self.llm_api = ModelAPI(self.llm_config)
        
        # 图片配置
        self.image_config = IMAGE_CONFIG
    
    def evaluate(self, protocol: Dict, images_dir: str, experiment_name: str,
                 physical_result: Optional[Dict] = None) -> Dict:
        """
        评估布局（30分）
        
        Args:
            protocol: 实验协议JSON
            images_dir: 图片目录路径
            experiment_name: 实验名称
            physical_result: 物理评估结果（可选，用于交叉验证）
        
        Returns:
            result: 包含总分、问题评分、详细信息的字典
        """
        result = {
            'total_score': 0,
            'max_score': 30,  # 修改为30分
            'average_score': 0,
            'category_breakdown': {},
            'questions': [],
            'low_score_items': []
        }
        
        # 1. 生成问题
        print("正在生成评估问题...")
        questions = self.question_generator.generate_questions(protocol)
        print(f"生成了{len(questions)}个问题")
        
        # 2. 加载图片
        print("正在加载渲染图片...")
        image_paths = find_experiment_images(
            images_dir,
            experiment_name,
            self.image_config['views'],
            self.image_config['format']
        )
        
        if len(image_paths) == 0:
            print("警告：未找到渲染图片，跳过语义评估")
            return result
        
        print(f"找到{len(image_paths)}张图片")
        
        # 3. 逐题评分
        print("正在进行LLM评分...")
        for i, question in enumerate(questions):
            print(f"评估问题 {i+1}/{len(questions)}...")
            
            question_result = self._evaluate_question(
                question,
                image_paths,
                protocol,
                physical_result
            )
            
            result['questions'].append(question_result)
            result['total_score'] += question_result['score']
            
            # 记录低分项（低于一半分数）
            if question_result['score'] < question_result['max_score'] / 2:
                result['low_score_items'].append({
                    'question_id': question_result['id'],
                    'score': question_result['score'],
                    'category': question_result['category'],
                    'issue': question_result['reason'][:100]  # 截取前100字
                })
            
            # 避免API限流
            time.sleep(1)
        
        # 4. 计算统计信息
        result['average_score'] = result['total_score'] / len(questions) if questions else 0
        result['category_breakdown'] = self._calculate_category_breakdown(result['questions'])
        
        return result
    
    def _evaluate_question(self, question: Dict, image_paths: Dict, protocol: Dict,
                          physical_result: Optional[Dict] = None) -> Dict:
        """
        评估单个问题
        
        Args:
            question: 问题定义
            image_paths: 图片路径字典
            protocol: 实验协议
            physical_result: 物理评估结果（可选）
        
        Returns:
            question_result: 包含评分和详细信息
        """
        # 准备prompt
        prompt = self._prepare_prompt(question, protocol, physical_result)
        
        # 准备图片（只加载该问题需要的视图）
        required_views = question.get('views', ['top_view', 'front_view'])
        images_base64 = {}
        for view in required_views:
            if view in image_paths:
                b64 = load_image_as_base64(image_paths[view])
                if b64:
                    images_base64[view] = b64
        
        # 调用LLM
        try:
            response = self._call_llm_with_images(prompt, images_base64)
            
            # 调试：打印LLM返回
            if not response or not response.strip():
                raise ValueError(f"LLM返回为空")
            
            # 提取JSON（LLM可能返回markdown格式）
            json_str = self._extract_json_from_response(response)
            
            # 尝试解析JSON
            try:
                llm_result = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"JSON解析失败。提取的JSON内容：{json_str[:500]}")
                raise ValueError(f"LLM返回不是有效的JSON: {e}")
            
            # 验证返回格式
            if 'score' not in llm_result:
                raise ValueError("LLM返回缺少score字段")
            
            # 组装结果
            return {
                'id': question['id'],
                'category': question['category'],
                'question': question['question'],
                'views': question['views'],
                'score': int(llm_result['score']),
                'max_score': question['max_score'],
                'reason': llm_result.get('reason', ''),
                'strengths': llm_result.get('strengths', []),
                'weaknesses': llm_result.get('weaknesses', []),
                'suggestions': llm_result.get('suggestions', [])
            }
        
        except Exception as e:
            print(f"警告：LLM评分失败：{e}，使用默认分数{question['max_score']//2}分")
            return {
                'id': question['id'],
                'category': question['category'],
                'question': question['question'],
                'views': question['views'],
                'score': question['max_score'] // 2,  # 使用中等分数
                'max_score': question['max_score'],
                'reason': f'LLM评分失败：{str(e)}',
                'strengths': [],
                'weaknesses': [],
                'suggestions': []
            }
    
    def _prepare_prompt(self, question: Dict, protocol: Dict, 
                       physical_result: Optional[Dict] = None) -> str:
        """
        准备LLM prompt
        
        Args:
            question: 问题定义
            protocol: 实验协议
            physical_result: 物理评估结果（可选）
        
        Returns:
            prompt: 完整的prompt文本
        """
        experiment_name = protocol.get('experiment_name', '')
        experiment_desc = protocol.get('experiment_description', '')
        
        prompt = f"""# Experiment Information
Experiment Name: {experiment_name}
Experiment Description: {experiment_desc}

# Scoring Task
Please score the following question based on the provided laboratory layout rendered images.

## Question
{question['question']}

## Available Views
- top_view: Top-down view for overall layout
- front_view: Front view from operator's perspective
- left_view: Left side view
- right_view: Right side view
- fume_hood_view: Fume hood close-up (if applicable)

Views required for this question: {', '.join(question['views'])}

{self._format_physical_hints(physical_result, question)}

## Scoring Criteria (Strict Adherence Required)
6 points - Excellent: Fully meets requirements, demonstrates best practices, no issues
5 points - Very Good: Meets requirements well with only trivial room for improvement
4 points - Good: Generally meets requirements with minor improvable issues
3 points - Acceptable: Meets basic requirements but has some noticeable issues
2 points - Poor: Partially meets requirements with significant issues
1 point - Very Poor: Barely meets minimal requirements with major issues
0 points - Unacceptable: Has critical safety hazards or completely fails requirements

## Output Requirements
Please output the scoring result in JSON format with the following fields:

{{
  "score": <integer, 0-6>,
  "reason": "<detailed scoring rationale, 150-250 words, must specify scoring basis>",
  "strengths": ["<strength 1>", "<strength 2>"],
  "weaknesses": ["<issue 1>", "<issue 2>"],
  "suggestions": ["<improvement suggestion 1>", "<improvement suggestion 2>"]
}}

## Important Notes
1. Scoring must be strict and objective, based on chemical laboratory safety regulations
2. Reasons must be specific, citing visible details in the images
3. **CRITICAL**: If physical constraint check results are provided above, use them as reference data:
   - When visual assessment conflicts with physical measurements, trust the physical data
   - If you cannot clearly see an object's location in images but physical check confirms it, note this discrepancy in your reason
   - Example: "Although HCl bottle is not clearly visible in fume_hood_view, physical constraint check (C3) confirms it is located inside FumeHood with 100% satisfaction"
4. If image information is insufficient AND no physical reference is available, explain in the reason field and give a moderate score (2 points)
5. Safety issues must be scored strictly
6. Output JSON only, no other text
7. All special characters in strings must be properly escaped
8. The output JSON must be a complete code block
"""
        return prompt
    
    def _format_physical_hints(self, physical_result: Optional[Dict], question: Dict) -> str:
        """
        根据问题类型格式化物理约束检查结果作为参考提示
        
        Args:
            physical_result: 物理评估结果
            question: 当前问题
        
        Returns:
            formatted_hints: 格式化的提示文本
        """
        if not physical_result:
            return ""
        
        hints = []
        question_text = question.get('question', '').lower()
        
        # 提取化学约束结果
        chemical_eval = physical_result.get('chemical_constraints', {})
        constraint_results = chemical_eval.get('constraint_results', [])
        
        # 根据问题内容匹配相关约束
        relevant_constraints = []
        
        # 检测问题中提到的物品名称
        for constraint in constraint_results:
            details = constraint.get('details', {})
            
            # C3约束：挥发性试剂通风
            if constraint.get('constraint_type') == 'C3':
                # 提取试剂名称
                expected = details.get('expected', '')
                actual = details.get('actual', '')
                
                # 检查问题中是否提到该试剂
                for keyword in ['ethanol', 'hydrochloricacid', 'sodiumhydroxide', 'volatile', 'toxic']:
                    if keyword in question_text.replace(' ', '').replace('_', '').lower():
                        relevant_constraints.append({
                            'type': 'C3 (Volatile/Toxic Reagent Ventilation)',
                            'satisfaction': constraint.get('satisfaction', 0),
                            'passed': constraint.get('passed', False),
                            'expected': expected,
                            'actual': actual
                        })
                        break
            
            # C1约束：易燃物与热源分离
            elif constraint.get('constraint_type') == 'C1':
                if 'flammable' in question_text or 'heat' in question_text or 'ethanol' in question_text:
                    relevant_constraints.append({
                        'type': 'C1 (Flammable-Heat Separation)',
                        'satisfaction': constraint.get('satisfaction', 0),
                        'passed': constraint.get('passed', False),
                        'expected': details.get('expected', ''),
                        'actual': details.get('actual', '')
                    })
            
            # C5约束：不兼容试剂分离
            elif constraint.get('constraint_type') == 'C5':
                if 'incompatible' in question_text or 'separation' in question_text:
                    relevant_constraints.append({
                        'type': 'C5 (Incompatible Reagent Separation)',
                        'satisfaction': constraint.get('satisfaction', 0),
                        'passed': constraint.get('passed', False),
                        'expected': details.get('expected', ''),
                        'actual': details.get('actual', '')
                    })
            
            # C6约束：酸碱分离
            elif constraint.get('constraint_type') == 'C6':
                if 'acid' in question_text or 'base' in question_text:
                    relevant_constraints.append({
                        'type': 'C6 (Acid-Base Separation)',
                        'satisfaction': constraint.get('satisfaction', 0),
                        'passed': constraint.get('passed', False),
                        'expected': details.get('expected', ''),
                        'actual': details.get('actual', '')
                    })
        
        # 如果找到相关约束，格式化输出
        if relevant_constraints:
            hints.append("## Physical Constraint Check Results (Reference)")
            hints.append("The following physical measurements have been verified programmatically:")
            hints.append("")
            
            for i, constraint in enumerate(relevant_constraints, 1):
                status = "✓ PASSED" if constraint['passed'] else "✗ FAILED"
                satisfaction_pct = constraint['satisfaction'] * 100
                
                hints.append(f"{i}. **{constraint['type']}** - {status} ({satisfaction_pct:.1f}% satisfaction)")
                hints.append(f"   - Expected: {constraint['expected']}")
                hints.append(f"   - Actual: {constraint['actual']}")
                hints.append("")
            
            hints.append("**Note**: These measurements are obtained from precise 3D coordinate calculations.")
            hints.append("If visual assessment from images conflicts with these results, prioritize the physical data")
            hints.append("and note the visual limitation in your evaluation reason.")
            hints.append("")
        
        return "\n".join(hints)
    
    def _extract_json_from_response(self, response: str) -> str:
        """
        从LLM响应中提取JSON内容
        LLM可能返回markdown格式：```json ... ```
        
        Args:
            response: LLM原始响应
        
        Returns:
            json_str: 纯JSON字符串
        """
        response = response.strip()
        
        # 如果是markdown格式，提取代码块中的内容
        if response.startswith('```'):
            # 找到第一个换行（跳过```json）
            start = response.find('\n')
            if start == -1:
                return response
            # 找到结束的```
            end = response.rfind('```')
            if end == -1:
                return response[start:].strip()
            return response[start:end].strip()
        
        return response
    
    def _call_llm_with_images(self, prompt: str, images_base64: Dict[str, str]) -> str:
        """
        调用LLM API（带图片）
        
        Args:
            prompt: 文本prompt
            images_base64: {view_name: base64_string}
        
        Returns:
            response: LLM返回的JSON字符串
        """
        # 构建消息
        system_prompt = """You are an experienced chemical laboratory safety expert and laboratory design consultant with the following professional background:
- Over 15 years of chemical laboratory management experience
- Proficient in laboratory safety regulations and layout design
- Familiar with the properties and safety requirements of various chemical reagents
- Expertise in ergonomics and spatial design

Your task is to professionally evaluate chemical laboratory layouts and provide objective, accurate scoring and recommendations."""
        
        # 构建内容列表
        content = [{"type": "text", "text": prompt}]
        
        # 添加图片
        for view_name, base64_str in images_base64.items():
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64_str}"
                }
            })
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ]
        
        # 直接使用OpenAI客户端调用（支持图片）
        try:
            response = self.llm_api.client.chat.completions.create(
                model=self.llm_api.config.model,
                messages=messages,
                temperature=self.llm_api.config.temperature,
                max_tokens=self.llm_api.config.max_tokens
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            raise Exception(f"调用大模型API失败: {str(e)}")
    
    def _calculate_category_breakdown(self, questions: List[Dict]) -> Dict:
        """
        计算各类别的得分统计
        
        Args:
            questions: 问题列表
        
        Returns:
            breakdown: 各类别统计
        """
        categories = {}
        
        for q in questions:
            category = q['category']
            if category not in categories:
                categories[category] = {
                    'score': 0,
                    'max': 0,
                    'count': 0
                }
            
            categories[category]['score'] += q['score']
            categories[category]['max'] += q['max_score']
            categories[category]['count'] += 1
        
        return categories

