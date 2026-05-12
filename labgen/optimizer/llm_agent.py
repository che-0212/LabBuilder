"""
LLM 交互模块
"""

import json
import logging
from pathlib import Path
from typing import Dict, List

from utils.llm_config import LLMConfig, ModelAPI
from labgen.optimizer.config import OPTIMIZER_CONFIG

logger = logging.getLogger(__name__)


class LLMAgent:
    """调用 LLM 生成优化建议"""

    def __init__(self, asset_library: Dict = None) -> None:
        config = LLMConfig(
            model=OPTIMIZER_CONFIG["llm_model"],
            temperature=OPTIMIZER_CONFIG["llm_temperature"],
            max_tokens=OPTIMIZER_CONFIG["llm_max_tokens"],
        )
        self.api = ModelAPI(config)
        self.asset_library = asset_library or {}

    def _get_asset_bbox(self, asset_id: str) -> Dict:
        """从资产库获取bbox信息"""
        assets_list = self.asset_library.get('assets', [])
        for asset in assets_list:
            if asset.get('id') == asset_id:
                geometry = asset.get('geometry', {})
                bbox = geometry.get('bbox', {})
                if bbox:
                    return {
                        'short': bbox.get('short', 0),
                        'long': bbox.get('long', 0),
                        'height': bbox.get('height', 0)
                    }
        return None

    def _analyze_wall_usage(self, layout: Dict) -> Dict:
        """分析当前墙占用情况"""
        wall_usage = {
            'west': [],   # x接近0.2
            'east': [],   # x接近8.39
            'south': [],  # y接近0.2
            'north': []   # y接近8.74
        }
        
        for obj in layout.get("objects", []):
            if obj.get("initial_location") != "floor":
                continue
            
            asset_id = obj.get("id")
            pos = obj.get("position", {})
            x = float(pos.get("x", 0.0))
            y = float(pos.get("y", 0.0))
            
            # 判断靠近哪面墙（考虑20cm墙厚）
            if abs(x - 0.2) < 0.5:  # 西墙
                wall_usage['west'].append(asset_id)
            elif abs(x - 8.39) < 0.5:  # 东墙
                wall_usage['east'].append(asset_id)
            elif abs(y - 0.2) < 0.5:  # 南墙
                wall_usage['south'].append(asset_id)
            elif abs(y - 8.74) < 0.5:  # 北墙
                wall_usage['north'].append(asset_id)
        
        return wall_usage

    def _get_work_surface_bounds(self, layout: Dict, surface_id: str) -> Dict:
        """
        获取工作台的有效边界范围（局部坐标系）
        
        Args:
            layout: 布局JSON
            surface_id: 工作台ID
        
        Returns:
            边界信息 {'x_min', 'x_max', 'y_min', 'y_max', 'z'} 或 None
        """
        # 查找工作台
        surface_obj = None
        for obj in layout.get("objects", []):
            if obj.get("id") == surface_id and obj.get("initial_location") == "floor":
                surface_obj = obj
                break
        
        if not surface_obj:
            return None
        
        # 获取工作台尺寸
        bbox = self._get_asset_bbox(surface_id)
        if not bbox:
            return None
        
        # 获取工作台位置和旋转
        pos = surface_obj.get("position", {})
        rot = surface_obj.get("rotation", {})
        surface_x = float(pos.get("x", 0))
        surface_y = float(pos.get("y", 0))
        rot_z = float(rot.get("z", 0))
        
        short_side = bbox.get('short', 0)
        long_side = bbox.get('long', 0)
        height = bbox.get('height', 0.8)
        
        # 根据旋转角度确定实际X/Y方向的尺寸
        # 0°/180°: long边平行X轴，short边平行Y轴
        # 90°/270°: long边平行Y轴，short边平行X轴
        if rot_z in [0, 180]:
            half_x = long_side / 2
            half_y = short_side / 2
        else:  # 90, 270
            half_x = short_side / 2
            half_y = long_side / 2
        
        # 计算有效工作区域（留5cm边缘）
        margin = 0.05
        return {
            'x_min': surface_x - half_x + margin,
            'x_max': surface_x + half_x - margin,
            'y_min': surface_y - half_y + margin,
            'y_max': surface_y + half_y - margin,
            'z': height,
            'center_x': surface_x,
            'center_y': surface_y
        }

    def _build_layout_overview(self, layout: Dict, optimize_mode: str = "desktop") -> str:
        """精简版：只列出对象ID和位置"""
        lines = []
        for obj in layout.get("objects", []):
            asset_id = obj.get("id")
            is_floor = obj.get("initial_location") == "floor"
            
            # 根据优化模式过滤
            if optimize_mode == "room" and not is_floor:
                continue
            elif optimize_mode == "desktop" and is_floor:
                continue
            
            pos = obj.get("position", {})
            location = obj.get("initial_location", "unknown")
            x = float(pos.get("x", 0.0))
            y = float(pos.get("y", 0.0))
            z = float(pos.get("z", 0.0))
            
            if is_floor:
                lines.append(f"- {asset_id}: ({x:.2f}, {y:.2f}, {z:.2f})")
            else:
                lines.append(f"- {asset_id} @ {location}: ({x:.2f}, {y:.2f}, {z:.2f})")
        
        return "\n".join(lines)

    def _enhance_collision_info(self, evaluation_summary: str, layout: Dict) -> str:
        """增强评估摘要中的碰撞信息，添加对象位置"""
        import re
        
        # 查找所有Room Asset Collision信息
        pattern = r'\[Room Asset Collision\] (\w+) and (\w+) overlap on floor \(overlap area ≈ ([\d.]+) cm²\)\.'
        
        def replace_collision(match):
            obj_a, obj_b, overlap = match.groups()
            # 从layout中查找这两个对象的位置
            pos_a = None
            pos_b = None
            for obj in layout.get("objects", []):
                if obj.get("id") == obj_a and obj.get("initial_location") == "floor":
                    pos = obj.get("position", {})
                    pos_a = (float(pos.get("x", 0)), float(pos.get("y", 0)))
                elif obj.get("id") == obj_b and obj.get("initial_location") == "floor":
                    pos = obj.get("position", {})
                    pos_b = (float(pos.get("x", 0)), float(pos.get("y", 0)))
            
            if pos_a and pos_b:
                return (f"[Room Asset Collision] {obj_a} (at ({pos_a[0]:.3f}, {pos_a[1]:.3f})) and "
                       f"{obj_b} (at ({pos_b[0]:.3f}, {pos_b[1]:.3f})) overlap on floor "
                       f"(overlap area ≈ {overlap} cm²).")
            else:
                return match.group(0)  # 如果找不到位置，返回原文本
        
        enhanced = re.sub(pattern, replace_collision, evaluation_summary)
        return enhanced

    def _build_prompt(self, layout: Dict, evaluation_summary: str, optimize_mode: str = "desktop", auto_fix_report: Dict = None, protocol_location_guidance: Dict = None) -> str:
        """
        构建优化提示
        
        Args:
            layout: 布局JSON
            evaluation_summary: 评估摘要
            optimize_mode: 'room' (优化房间资产) 或 'desktop' (优化桌面物体)
        """
        layout_overview = self._build_layout_overview(layout, optimize_mode)
        
        if optimize_mode == "room":
            object_type = "room assets"
            constraints_text = "- Room bounds: x∈[0.2,8.39]m, y∈[0.2,8.74]m"
        else:
            object_type = "desktop objects"
            
            # 收集所有工作台及其边界信息
            work_surfaces_info = []
            work_surface_ids = set()
            for obj in layout.get("objects", []):
                if obj.get("initial_location") != "floor":
                    work_surface_ids.add(obj.get("initial_location", ""))
            
            for surface_id in work_surface_ids:
                bounds = self._get_work_surface_bounds(layout, surface_id)
                if bounds:
                    work_surfaces_info.append(
                        f"- **{surface_id}**: valid range x=[{bounds['x_min']:.2f}, {bounds['x_max']:.2f}], "
                        f"y=[{bounds['y_min']:.2f}, {bounds['y_max']:.2f}], z={bounds['z']:.2f}m (table height)"
                    )
            
            work_surfaces_text = "\n".join(work_surfaces_info) if work_surfaces_info else "- No work surface bounds available"
            
            constraints_text = f"""
**Surface bounds (objects must stay within):**
{work_surfaces_text}

**Guidelines:**
- Minimum spacing: 5cm between objects
- Standard desktop height: z=0.8m (or as specified for the surface)
"""
        
        # 提取critical_fixes（如果存在）
        critical_fixes_text = ""
        if "🔴 CRITICAL FIXES" in evaluation_summary:
            # evaluation_summary已经包含了critical_fixes的详细说明
            critical_fixes_text = ""  # 不需要额外添加
        
        # 精简版prompt：只包含核心信息
        prompt = f"""
Laboratory layout optimization. Fix the issues listed in the evaluation.

## Current {object_type}:
{layout_overview}

## Issues to fix:
{evaluation_summary}

## Constraints:
{constraints_text}

## Output (JSON array):
{{
  "id": "<object_id>",
  "position": {{"x": <float>, "y": <float>, "z": <float>}},
  "initial_location": "<work_surface_id or 'floor'>",  // REQUIRED if relocating object to different surface
  "reason": "<why>"
}}

**PRIORITY ORDER**:
1. **CRITICAL FIXES** (if any): Must be fixed first - highest priority
2. **REAGENT STORAGE REQUIREMENT** (if any): High priority - relocate reagents to proper storage
3. **Other optimization suggestions**: Medium priority - improve safety and efficiency

**IMPORTANT**: 
- Address issues in priority order
- For CRITICAL FIXES: adjust the mentioned objects immediately
- For REAGENT STORAGE REQUIREMENT: relocate reagents to ReagentCabinet and arrange according to the 4-layer rule
- Return [] only if there are absolutely no issues to fix
        """.strip()
        return prompt

    def _sanitize_summary(self, summary: str) -> str:
        """
        清理评估摘要，减少内容审核误判的风险
        
        策略：替换可能触发审核的词汇为更中性的术语
        """
        # 创建替换映射（将敏感词替换为通用术语）
        replacements = {
            # 注意：这里不要过度替换，只处理确实可能被误判的情况
            # 大多数化学名称是安全的，只有某些组合可能被误判
        }
        
        sanitized = summary
        for old, new in replacements.items():
            sanitized = sanitized.replace(old, new)
        
        return sanitized
    
    def request_adjustments(self, layout: Dict, evaluation_summary: str, optimize_mode: str = "desktop", auto_fix_report: Dict = None, protocol_location_guidance: Dict = None) -> List[Dict]:
        """
        请求LLM提供优化建议
        
        Args:
            layout: 布局JSON
            evaluation_summary: 评估摘要
            optimize_mode: 'room' (优化房间资产) 或 'desktop' (优化桌面物体)
        """
        # 清理评估摘要（减少内容审核误判风险）
        sanitized_summary = self._sanitize_summary(evaluation_summary)
        prompt = self._build_prompt(layout, sanitized_summary, optimize_mode, auto_fix_report=auto_fix_report, protocol_location_guidance=protocol_location_guidance)
        response_text = self.api.call(prompt)
        
        # 检查空响应
        if not response_text or len(response_text.strip()) == 0:
            logger.warning("LLM returned empty response, no adjustments to apply")
            return []
        
        cleaned = self._extract_json(response_text)

        try:
            adjustments = json.loads(cleaned)
            if not isinstance(adjustments, list):
                raise ValueError("LLM 返回的数据不是 JSON 数组")
            return adjustments
        except json.JSONDecodeError as exc:
            # 尝试修复常见的JSON格式错误
            logger.warning(f"JSON解析失败，尝试修复: {exc}")
            try:
                fixed = self._fix_json_errors(cleaned)
                adjustments = json.loads(fixed)
                if not isinstance(adjustments, list):
                    raise ValueError("LLM 返回的数据不是 JSON 数组")
                logger.info("✓ JSON修复成功")
                return adjustments
            except Exception as fix_exc:
                logger.error(f"JSON修复失败: {fix_exc}")
                # 保存失败的响应用于调试
                debug_file = Path("/tmp/llm_response_error.txt")
                with open(debug_file, "w") as f:
                    f.write(f"Original response:\n{response_text}\n\n")
                    f.write(f"Cleaned:\n{cleaned}\n\n")
                    f.write(f"Error: {exc}\n")
                raise ValueError(f"无法解析 LLM 返回的 JSON: {exc}\n(已保存到 {debug_file})") from exc

    @staticmethod
    def _fix_json_errors(json_str: str) -> str:
        """修复常见的JSON格式错误"""
        import re
        
        # 1. 移除JSON中的注释 (// 和 /* */)
        json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)  # 单行注释
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)  # 多行注释
        
        # 2. 修复尾随逗号 (trailing commas)
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        # 3. 修复缺失的逗号 (在 } 或 ] 后面紧跟 { 或 [)
        json_str = re.sub(r'([}\]])(\s*)([{\[])', r'\1,\2\3', json_str)
        
        # 4. 修复缺失的逗号 (在字符串后面紧跟字符串)
        json_str = re.sub(r'(")([\s\n]+)(")', r'\1,\2\3', json_str)
        
        # 5. 修复单引号为双引号
        # 注意：这个可能会误伤字符串内容中的单引号，所以要小心
        # json_str = json_str.replace("'", '"')
        
        return json_str
    
    @staticmethod
    def _extract_json(response: str) -> str:
        text = response.strip()
        
        # 首先尝试查找 ```json 或 ``` 代码块
        json_start_markers = ["```json", "```"]
        for marker in json_start_markers:
            start_idx = text.find(marker)
            if start_idx != -1:
                # 找到开始标记，跳过标记本身
                content_start = start_idx + len(marker)
                # 跳过可能的换行
                if content_start < len(text) and text[content_start] == '\n':
                    content_start += 1
                # 查找结束标记
                end_idx = text.find("```", content_start)
                if end_idx != -1:
                    return text[content_start:end_idx].strip()
                else:
                    # 如果没有找到结束标记，可能是被截断了
                    # 直接提取从开始标记到文本末尾的内容
                    return text[content_start:].strip()
        
        # 如果没有代码块，尝试查找 JSON 数组的开始和结束
        # 查找第一个 '['
        start_idx = text.find('[')
        if start_idx != -1:
            # 从 '[' 开始，找到匹配的 ']'
            bracket_count = 0
            for i in range(start_idx, len(text)):
                if text[i] == '[':
                    bracket_count += 1
                elif text[i] == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        return text[start_idx:i+1].strip()
            
            # 如果没有找到匹配的]，可能是被截断了
            # 返回从[开始到文本末尾的内容（让JSON解析器处理错误）
            return text[start_idx:].strip()
        
        # 如果都找不到，返回原始文本（可能是纯JSON）
        return text.strip()
