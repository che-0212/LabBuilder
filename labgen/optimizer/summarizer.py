"""
Convert evaluation reports into English summaries for the LLM.
"""

import re
from typing import Dict, List


def _ascii_only(text: str) -> str:
    """Strip non-ASCII characters to avoid Chinese content in prompts."""
    return re.sub(r"[^\x20-\x7E]+", " ", text).strip()


class EvaluationSummarizer:
    """Build English summaries from evaluator output."""

    def __init__(self, evaluation_report: Dict) -> None:
        self.report = evaluation_report

    def overall_score_summary(self) -> str:
        scores = self.report.get("scores", {})
        total = scores.get("total")
        physical = scores.get("physical")
        semantic = scores.get("semantic")
        grade = scores.get("grade")
        passed = scores.get("passed")

        status = "passed" if passed else "failed"
        return "\n".join(
            [
                f"- Total score: {total} / {scores.get('max_score', 100)} (grade {grade}, {status})",
                f"- Physical score: {physical} / 70",
                f"- Semantic score: {semantic} / 30",
            ]
        )

    def physical_violations(self) -> List[str]:
        lines: List[str] = []
        physical = self.report.get("physical_evaluation", {})
        constraints = physical.get("physical_constraints", {})

        boundary = constraints.get("boundary", {})
        for item in boundary.get("violations", []):
            expected = _ascii_only(item.get("expected", ""))
            actual = _ascii_only(item.get("actual", ""))
            lines.append(
                f"[Boundary] {item.get('object')} on {item.get('work_surface')} "
                f"is outside the allowed range ({actual}); expected {expected}."
            )

        collision = constraints.get("collision", {})
        for item in collision.get("violations", []):
            obj_a, obj_b = item.get("objects", ["?", "?"])
            overlap = item.get("overlap_area")
            overlap_str = f"{float(overlap):.2f}" if isinstance(overlap, (int, float)) else overlap
            lines.append(
                f"[Collision] {obj_a} and {obj_b} overlap on {item.get('work_surface')} "
                f"(overlap area ≈ {overlap_str})."
            )

        height = constraints.get("height", {})
        for item in height.get("violations", []):
            actual = item.get("actual_height")
            expected = item.get("expected_height")
            lines.append(
                f"[Height] {item.get('object')} has z={actual}, expected {expected}."
            )

        # 添加房间资产违规（floor物体边界和碰撞）
        room_assets = constraints.get("room_assets", {})
        for item in room_assets.get("violations", []):
            constraint_type = item.get("constraint", "")
            
            if constraint_type == "room_boundary_check":
                # 边界违规：单个对象超出房间边界
                obj = item.get("object", "?")
                out_distance = item.get("out_of_bounds_distance", 0)
                expected = _ascii_only(item.get("expected", ""))
                lines.append(
                    f"[Room Asset Boundary] {obj} is outside room bounds "
                    f"(out by {out_distance:.1f}cm); expected {expected}."
                )
            elif constraint_type == "room_collision_check":
                # 碰撞违规：两个对象重叠
                objects = item.get("objects", [])
                if len(objects) >= 2:
                    obj_a, obj_b = objects[0], objects[1]
                else:
                    obj_a, obj_b = "?", "?"
                
                overlap = item.get("overlap_area")
                if isinstance(overlap, (int, float)):
                    overlap_str = f"{overlap:.2f}"
                else:
                    overlap_str = "unknown"
                
                lines.append(
                    f"[Room Asset Collision] {obj_a} and {obj_b} overlap on floor "
                    f"(overlap area ≈ {overlap_str} cm²)."
                )
            else:
                # 未知类型的违规，尝试通用格式
                obj = item.get("object") or item.get("objects", ["?", "?"])[0] if item.get("objects") else "?"
                expected = _ascii_only(item.get("expected", ""))
                actual = _ascii_only(item.get("actual", ""))
                lines.append(
                    f"[Room Asset Issue] {obj}: {actual}; expected {expected}."
                )

        return lines

    def chemical_violations(self) -> List[str]:
        lines: List[str] = []
        # 修复：化学约束在 physical_evaluation 下的 chemical_constraints 中
        physical = self.report.get("physical_evaluation", {})
        chemical = physical.get("chemical_constraints", {})
        
        # 遍历化学约束结果
        for item in chemical.get("constraint_results", []):
            # 只处理未通过的约束（passed=False 或 satisfaction < 0.8）
            if item.get("passed", True):
                continue
            
            constraint_type = item.get("constraint_type", "")
            description = _ascii_only(item.get("description", ""))
            details = item.get("details", {})
            expected = _ascii_only(details.get("expected", ""))
            actual = _ascii_only(details.get("actual", ""))
            satisfaction = item.get("satisfaction", 1.0)
            
            lines.append(
                f"[Chemical Constraint {constraint_type}] {description}: {actual}; "
                f"expected {expected} (satisfaction: {satisfaction:.2f})"
            )
        
        return lines

    def semantic_feedback(self) -> List[str]:
        lines: List[str] = []
        semantic = self.report.get("semantic_evaluation", {})
        questions = semantic.get("questions", [])
        for q in questions:
            score = q.get("score", 0)
            max_score = q.get("max_score", 5)
            if score >= max_score:
                continue
            lines.append(f"[Semantic] Question: {q.get('question')}")
            lines.append(f"  - Score: {score}/{max_score}")
            reason = q.get("reason", "")
            if reason:
                lines.append(f"  - Reason: {_ascii_only(reason)}")
            suggestions = q.get("suggestions", [])
            if suggestions:
                lines.append("  - Suggestions:")
                for suggestion in suggestions:
                    lines.append(f"    * {_ascii_only(suggestion)}")
        return lines

    def improvement_suggestions_summary(self) -> List[str]:
        """提取评估器给出的改进建议"""
        suggestions = self.report.get("improvement_suggestions", {})
        lines = []
        
        # 优先显示紧急建议
        for item in suggestions.get("immediate", [])[:5]:
            lines.append(f"[URGENT] {_ascii_only(item)}")
        
        # 然后是推荐建议
        for item in suggestions.get("recommended", [])[:3]:
            lines.append(f"[RECOMMENDED] {_ascii_only(item)}")
        
        return lines

    def build_summary(self, auto_fix_report: Dict = None) -> str:
        blocks = [
            "## Evaluation Overview",
            self.overall_score_summary(),
        ]
        
        # === Priority 1: CRITICAL FIXES (Location Mismatch) ===
        critical_fixes = self.report.get('improvement_suggestions', {}).get('critical_fixes', [])
        location_fixes = [f for f in critical_fixes if f.get('type') == 'location_mismatch_batch']
        
        if location_fixes:
            # 如果location mismatch太多，只处理第一个surface（分批处理）
            if len(location_fixes) > 1:
                total_objects = sum(len(f.get('objects', [])) for f in location_fixes)
                if total_objects > 8:  # 超过8个对象，只处理第一组
                    blocks.append("\n## 🔴 CRITICAL FIXES (HIGHEST PRIORITY - Location Mismatch)")
                    blocks.append(f"⚠️ 检测到{len(location_fixes)}组共{total_objects}个位置错误。")
                    blocks.append("为避免响应过长，本次只处理第一组，其余将在后续迭代中处理。")
                    blocks.append("")
                    location_fixes = location_fixes[:1]  # 只保留第一组
            
            blocks.append("\n## 🔴 CRITICAL FIXES (Location Mismatch - Must fix by re-layout)")
            blocks.append("These objects are marked for one surface but physically located elsewhere:")
            blocks.append("")
            
            for i, fix in enumerate(location_fixes, 1):
                blocks.append(f"{i}. Surface: {fix['surface']}")
                blocks.append(f"   Affected objects ({len(fix['objects'])}): {', '.join(fix['objects'])}")
                blocks.append(f"   Issue: {fix['issue']}")
                blocks.append(f"   Suggestion: {fix['suggestion']}")
                blocks.append("")

        physical = self.physical_violations()
        if physical:
            blocks.append("\n## Physical Violations")
            blocks.extend(f"- {line}" for line in physical)

            # === Priority 3: Chemical Safety Issues ===
            chemical = self.chemical_violations()
            if chemical:
                blocks.append("\n## Chemical Safety Issues")
                blocks.extend(f"- {line}" for line in chemical)

            semantic = self.semantic_feedback()
            if semantic:
                blocks.append("\n## Semantic Feedback")
                blocks.extend(f"- {line}" for line in semantic)

        # Add optimization suggestions (moved outside 'if physical' block - should always be processed)
        optimization = self.report.get('improvement_suggestions', {}).get('optimization', [])
        if optimization:
            # 特别处理试剂分层建议
            reagent_layering = [opt for opt in optimization if opt.get('type') == 'reagent_layering']
            other_optimization = [opt for opt in optimization if opt.get('type') != 'reagent_layering']
            
            # 试剂分层建议作为高优先级指令
            if reagent_layering:
                blocks.append("\n## 🔵 REAGENT STORAGE REQUIREMENT (High Priority)")
                blocks.append("⚠️ IMPORTANT: The following reagents MUST be relocated to ReagentCabinet for proper storage:")
                blocks.append("")
                for opt in reagent_layering:
                    suggestion_text = opt.get('suggestion', '')
                    # 提取并强调关键信息
                    if suggestion_text:
                        blocks.append(suggestion_text)
                    blocks.append("")
                    blocks.append("🎯 ACTION REQUIRED:")
                    blocks.append("  1. Move each reagent from current location to ReagentCabinet")
                    blocks.append("  2. Update 'initial_location' field to 'reagent_cabinet'")
                    blocks.append("  3. Arrange reagents according to the 4-layer rule specified above")
                    blocks.append("  4. Use ~12cm spacing along x-axis within ReagentCabinet bounds")
                    blocks.append("")
            
            # 其他优化建议
            if other_optimization:
                blocks.append("\n## Other Optimization Suggestions")
                for i, opt in enumerate(other_optimization, 1):
                    blocks.append(f"{i}. {opt.get('suggestion', opt.get('expected', ''))}")

        # 添加自动化修复报告
        if auto_fix_report:
            blocks.append("\n## Automated Fix Results")
            blocks.append(f"- Initial violations: {auto_fix_report.get('initial_violation_count', 0)}")
            blocks.append(f"- Final violations: {auto_fix_report.get('final_violation_count', 0)}")
            blocks.append(f"- Improvement: {auto_fix_report.get('improvement', 0)} violations fixed")
            blocks.append(f"- Fix rounds: {auto_fix_report.get('fix_rounds', 0)}")
            
            remaining_collisions = auto_fix_report.get('remaining_collisions', [])
            if remaining_collisions:
                blocks.append(f"\n- Remaining collisions that need LLM attention ({len(remaining_collisions)}):")
                for i, collision in enumerate(remaining_collisions, 1):
                    objects = collision.get('objects', [])
                    overlap = collision.get('overlap_area', 0)
                    surface = collision.get('work_surface', 'unknown')
                    positions = collision.get('positions', {})
                    
                    pos_info = ""
                    if positions:
                        pos_list = []
                        for obj_id in objects:
                            if obj_id in positions:
                                pos = positions[obj_id]
                                pos_list.append(f"{obj_id} at ({pos.get('x', 0):.3f}, {pos.get('y', 0):.3f})")
                        if pos_list:
                            pos_info = f" - Positions: {', '.join(pos_list)}"
                    
                    blocks.append(
                        f"  {i}. {objects[0] if len(objects) > 0 else '?'} ↔ "
                        f"{objects[1] if len(objects) > 1 else '?'} on {surface} "
                        f"(overlap: {overlap:.1f} cm²){pos_info}"
                    )
                blocks.append(
                    "\n⚠️ IMPORTANT: These collisions could not be automatically resolved. "
                    "Please use your spatial reasoning to find better positions that:"
                )
                blocks.append("  1. Separate the objects by at least their combined radius + 2cm clearance")
                blocks.append("  2. Keep objects within their work surface boundaries")
                blocks.append("  3. Avoid introducing new collisions with other objects")
            else:
                blocks.append("- All collisions were automatically resolved ✓")

        return "\n".join(blocks)

    def violation_count(self) -> int:
        """计算所有物理和化学约束违规的总数"""
        physical = self.report.get("physical_evaluation", {})
        
        # 统计物理约束违规（边界、碰撞、高度）
        physical_constraints = physical.get("physical_constraints", {})
        count = 0
        for key in ["boundary", "collision", "height"]:
            count += len(physical_constraints.get(key, {}).get("violations", []))
        
        # 统计房间资产碰撞违规
        room_assets = physical_constraints.get("room_assets", {})
        count += len(room_assets.get("violations", []))
        
        # 统计化学约束违规
        chemical_constraints = physical.get("chemical_constraints", {})
        count += len(chemical_constraints.get("violations", []))
        
        return count



