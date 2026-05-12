"""
语义指标计算器
使用GPT-4o根据场景照片按照评分标准打分
"""

import os
import json
import sys
import base64
from pathlib import Path
from typing import Dict, List, Optional
from openai import OpenAI

# 添加父目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from utils.llm_config import DEFAULT_API_KEY, DEFAULT_BASE_URL


class SemanticMetrics:
    """语义指标计算器(使用GPT-4o视觉模型)"""
    
    # 评分标准
    SCORING_CRITERIA = {
        'realism': {
            'name': 'Real. (真实感)',
            'description': '真实感: 是否符合现实实验室的尺度与布局,是否像"真实存在的实验室"',
            'high': {
                'score_range': (8, 10),
                'criteria': [
                    '布局符合真实化学实验室规范',
                    '设备类型合理,无明显"外行式摆放"'
                ]
            },
            'medium': {
                'score_range': (4, 7),
                'criteria': ['设备基本正确,但比例或位置略不合理']
            },
            'low': {
                'score_range': (0, 3),
                'criteria': [
                    '出现实验室中不合理或危险的元素',
                    '明显违背实验常识'
                ]
            },
            'key_rule': '若设备组合明显违背实验室常识, Real. ≤ 5'
        },
        'functionality': {
            'name': 'Functionality. (功能性)',
            'description': '功能性: 实验室是否有能完成目标实验的功能',
            'high': {
                'score_range': (8, 10),
                'criteria': [
                    '所有关键功能区域齐全',
                    '可在该场景中完成目标实验流程'
                ]
            },
            'medium': {
                'score_range': (4, 7),
                'criteria': ['基本功能具备,但缺少辅助功能']
            },
            'low': {
                'score_range': (0, 3),
                'criteria': [
                    '缺失关键设施',
                    '实验流程无法完成'
                ]
            },
            'key_rule': '缺失任何一个"任务关键设备", Functionality. ≤ 5 (比如化学实验室没有通风橱)'
        },
        'layout': {
            'name': 'Layout. (布局合理性)',
            'description': '布局合理性',
            'high': {
                'score_range': (8, 10),
                'criteria': [
                    '动线清晰',
                    '危险设备位置合理',
                    '操作空间充足'
                ]
            },
            'medium': {
                'score_range': (4, 7),
                'criteria': ['局部拥挤或流程不顺']
            },
            'low': {
                'score_range': (0, 3),
                'criteria': [
                    '严重遮挡',
                    '碰撞、拥挤、危险混布'
                ]
            },
            'key_rule': '若布局问题会影响安全或实验可执行性, Layout.≤ 5'
        },
        'completion': {
            'name': 'Completion. (完整度)',
            'description': '完整度',
            'high': {
                'score_range': (8, 10),
                'criteria': [
                    '主设备+辅助设备齐全',
                    '实验台不"空"'
                ]
            },
            'medium': {
                'score_range': (4, 7),
                'criteria': ['主设备齐全,但辅助设备不足']
            },
            'low': {
                'score_range': (0, 3),
                'criteria': [
                    '场景稀疏',
                    '明显"未完成感"'
                ]
            },
            'key_rule': '若超过70%的实验台或墙面为空, Completion. ≤ 5'
        }
    }
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, scoring_mode: str = 'medium'):
        """
        初始化语义指标计算器
        
        Args:
            api_key: OpenAI API密钥
            base_url: API基础URL
            scoring_mode: 评分模式,'strict'(严格)、'medium'(中等)或'lenient'(宽松)
        """
        self.api_key = api_key or DEFAULT_API_KEY
        self.base_url = base_url or DEFAULT_BASE_URL
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.model = "claude-sonnet-4-20250514"
        self.scoring_mode = scoring_mode
    
    def _find_images(self, scene_dir: Path) -> List[Path]:
        """
        查找场景目录下的所有图片文件
        
        Args:
            scene_dir: 场景目录路径
        
        Returns:
            image_paths: 图片文件路径列表
        """
        image_extensions = ['.png', '.jpg', '.jpeg']
        images = []
        
        for ext in image_extensions:
            images.extend(list(scene_dir.glob(f"*{ext}")))
            images.extend(list(scene_dir.glob(f"*{ext.upper()}")))
        
        return sorted(images)
    
    def _encode_image(self, image_path: Path) -> str:
        """
        将图片编码为base64
        
        Args:
            image_path: 图片文件路径
        
        Returns:
            base64_string: base64编码的图片字符串
        """
        with open(image_path, 'rb') as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def _build_scoring_prompt(self, protocol: Optional[Dict] = None) -> str:
        """
        构建评分提示词
        
        Args:
            protocol: 实验协议字典(可选)
        
        Returns:
            prompt: 评分提示词
        """
        criteria_text = ""
        for key, criteria in self.SCORING_CRITERIA.items():
            criteria_text += f"\n### {criteria['name']}\n"
            criteria_text += f"**Standard Description**: {criteria['description']}\n\n"
            criteria_text += f"**8-10 points (High)**:\n"
            for item in criteria['high']['criteria']:
                criteria_text += f"  - {item}\n"
            criteria_text += f"\n**4-7 points (Medium)**: {criteria['medium']['criteria'][0]}\n"
            criteria_text += f"\n**0-3 points (Low)**:\n"
            for item in criteria['low']['criteria']:
                criteria_text += f"  - {item}\n"
            criteria_text += f"\n**Key Judgment Rule**: {criteria['key_rule']}\n"
        
        prompt = f"""You are an experienced chemical laboratory safety expert and laboratory design consultant. Please evaluate the laboratory layout based on the provided laboratory scene images according to the following scoring criteria."""
        
        # 添加protocol信息
        if protocol:
            experiment_name = protocol.get('experiment_name', 'Unknown Experiment')
            experiment_description = protocol.get('experiment_description', '')
            assets = protocol.get('assets', [])
            
            prompt += f"""

## Experiment Protocol Information

**Experiment Name**: {experiment_name}

**Experiment Description**: {experiment_description}

**Required Assets** (from protocol):
"""
            # 分类显示资产
            instruments = [a for a in assets if a.get('type') == 'instrument']
            reagents = [a for a in assets if a.get('type') == 'reagent']
            
            if instruments:
                prompt += f"\n**Instruments** ({len(instruments)} items):\n"
                for asset in instruments:
                    prompt += f"  - {asset.get('name', 'Unknown')}: {asset.get('purpose', 'N/A')}\n"
            
            if reagents:
                prompt += f"\n**Reagents** ({len(reagents)} items):\n"
                for asset in reagents:
                    prompt += f"  - {asset.get('name', 'Unknown')}: {asset.get('purpose', 'N/A')}\n"
            
            prompt += f"""

**Note**: All required assets from the protocol are present in the laboratory images. Use this information to understand what experiment this laboratory is designed for and evaluate whether the layout is appropriate for this specific experiment."""
        
        prompt += f"""

## Scoring Criteria

{criteria_text}

## Scoring Requirements

1. Carefully observe the laboratory layout in the images
2. If protocol information is provided, use it to understand the experiment context and evaluate whether the layout is appropriate for this specific experiment
3. Give a score of 0-10 points for each dimension (Real., Functionality., Layout., Completion.)
4. Scoring must strictly follow the above criteria"""
        
        # 根据评分模式添加不同的要求
        if self.scoring_mode == 'strict':
            prompt += """
5. **[STRICT MODE]** If the conditions in the key judgment rules are met, you MUST give a score ≤ 5
6. **[STRICT MODE]** For Functionality: The laboratory MUST have ALL critical equipment to complete the experiment, otherwise score ≤ 5
7. **[STRICT MODE]** For Completion: Missing ANY key reagents or equipment should significantly lower the score
8. **[STRICT MODE]** Be critical and identify any safety hazards or layout problems
9. Provide detailed scoring rationale based on the experiment requirements, highlighting any deficiencies
"""
        elif self.scoring_mode == 'medium':
            prompt += """
5. **[MEDIUM MODE]** If the conditions in the key judgment rules are met, give a score ≤ 5, but minor deviations are acceptable
6. **[MEDIUM MODE]** For Functionality: The laboratory should have most critical equipment; missing 1-2 minor pieces is acceptable but will lower the score
7. **[MEDIUM MODE]** For Completion: Missing some auxiliary reagents is acceptable, but missing key reagents should significantly impact the score
8. **[MEDIUM MODE]** Balance between identifying issues and recognizing what works well
9. Provide detailed scoring rationale, noting both strengths and weaknesses in a balanced manner
"""
        else:  # lenient mode
            prompt += """
5. **[LENIENT MODE]** If the conditions in the key judgment rules are met, consider giving a score ≤ 5, but allow exceptions for minor issues
6. **[LENIENT MODE]** For Functionality: As long as the laboratory has MOST critical equipment and can reasonably complete the core steps of the experiment, scores can be above 5
7. **[LENIENT MODE]** For Completion: Missing some auxiliary reagents or minor equipment is acceptable if the main apparatus is present
8. **[LENIENT MODE]** Focus on the overall feasibility rather than strict compliance with every detail
9. Provide detailed scoring rationale, emphasizing what IS present and functional rather than what is missing
"""
        
        prompt += """
## Output Format

Please output the scoring results in JSON format as follows:

```json
{
    "realism": {
        "score": 8,
        "reason": "Scoring rationale..."
    },
    "functionality": {
        "score": 7,
        "reason": "Scoring rationale, including verification of required assets..."
    },
    "layout": {
        "score": 9,
        "reason": "Scoring rationale..."
    },
    "completion": {
        "score": 8,
        "reason": "Scoring rationale, including which assets are present or missing..."
    }
}
```

Please ensure the output is valid JSON format without any markdown code block markers.
"""
        
        return prompt
    
    def evaluate_scene(self, scene_dir: Path, protocol: Optional[Dict] = None, scene_file: Optional[Path] = None, gemini_mode: bool = False) -> Dict:
        """
        评估单个场景

        Args:
            scene_dir: 场景目录路径
            protocol: 实验协议字典(可选)
            scene_file: 场景文件路径(可选,如果提供则只查找对应的图片)
            gemini_mode: 是否为gemini模式(查找view_top.png)

        Returns:
            result: 评估结果字典
        """
        # 查找图片
        if gemini_mode:
            # gemini模式：查找view_top.png
            view_top_png = scene_dir / "view_top.png"
            images = [view_top_png] if view_top_png.exists() else []
        elif scene_file:
            # 根据场景文件名查找对应的图片
            scene_name = scene_file.stem  # 如 exp_001
            images = []
            for ext in ['.png', '.jpg', '.jpeg', '.PNG', '.JPG', '.JPEG']:
                img_path = scene_file.parent / f"{scene_name}{ext}"
                if img_path.exists():
                    images.append(img_path)
        else:
            images = self._find_images(scene_dir)
        
        if len(images) == 0:
            return {
                'scene_dir': str(scene_dir),
                'has_images': False,
                'error': '未找到图片文件'
            }
        
        # 编码图片
        image_base64_list = []
        image_info = []
        for img_path in images:
            try:
                base64_str = self._encode_image(img_path)
                image_base64_list.append(base64_str)
                image_info.append({
                    'path': str(img_path),
                    'name': img_path.name
                })
            except Exception as e:
                return {
                    'scene_dir': str(scene_dir),
                    'has_images': True,
                    'error': f'图片编码失败: {str(e)}'
                }
        
        # 构建提示词
        prompt = self._build_scoring_prompt(protocol)
        
        # 构建消息内容
        content = [{"type": "text", "text": prompt}]
        
        # 添加所有图片
        for base64_str in image_base64_list:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64_str}"
                }
            })
        
        messages = [
            {
                "role": "user",
                "content": content
            }
        ]
        
        # 调用GPT-4o API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=2000
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # 解析JSON响应
            # 尝试提取JSON部分(可能包含在代码块中)
            json_text = response_text
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                json_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                json_text = response_text[start:end].strip()
            
            scores = json.loads(json_text)
            
            # 计算总分
            total_score = sum([
                scores.get('realism', {}).get('score', 0),
                scores.get('functionality', {}).get('score', 0),
                scores.get('layout', {}).get('score', 0),
                scores.get('completion', {}).get('score', 0)
            ])
            
            return {
                'scene_dir': str(scene_dir),
                'has_images': True,
                'image_count': len(images),
                'images': image_info,
                'scores': scores,
                'total_score': total_score,
                'max_score': 40,
                'average_score': total_score / 4 if total_score > 0 else 0
            }
            
        except json.JSONDecodeError as e:
            return {
                'scene_dir': str(scene_dir),
                'has_images': True,
                'error': f'JSON解析失败: {str(e)}',
                'raw_response': response_text[:500]  # 只保存前500字符
            }
        except Exception as e:
            return {
                'scene_dir': str(scene_dir),
                'has_images': True,
                'error': f'API调用失败: {str(e)}'
            }

